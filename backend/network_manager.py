"""
Network management for Ubuntu Server using native tools (netplan, ip, iw)
"""
import json
import os
import re
import subprocess
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any

class UbuntuNetworkManager:
    """Manage network configuration on Ubuntu Server"""
    
    def __init__(self):
        self.netplan_dir = Path("/etc/netplan")
        
    def get_network_interfaces(self) -> Dict[str, Any]:
        """Get all network interfaces and their status using ip command"""
        interfaces = {}
        
        try:
            # Get interface list with JSON output
            result = subprocess.run(
                ["ip", "-j", "link", "show"],
                capture_output=True, text=True, check=True
            )
            
            links = json.loads(result.stdout)
            
            # Get IP addresses
            addr_result = subprocess.run(
                ["ip", "-j", "addr", "show"],
                capture_output=True, text=True, check=True
            )
            
            addresses = json.loads(addr_result.stdout)
            addr_map = {addr['ifname']: addr for addr in addresses}
            
            for link in links:
                ifname = link.get('ifname', '')
                # Skip loopback and virtual interfaces
                if ifname == 'lo' or ifname.startswith(('veth', 'docker', 'br-')):
                    continue
                    
                interface_info = {
                    'name': ifname,
                    'state': link.get('operstate', 'UNKNOWN'),
                    'mac': link.get('address', ''),
                    'type': 'ethernet' if 'eth' in ifname or 'eno' in ifname or 'enp' in ifname else 'wifi' if 'wl' in ifname else 'unknown',
                    'ip_addresses': []
                }
                
                # Add IP addresses if available
                if ifname in addr_map:
                    addr_info = addr_map[ifname]
                    for addr in addr_info.get('addr_info', []):
                        if addr.get('family') == 'inet':  # IPv4
                            interface_info['ip_addresses'].append({
                                'address': addr.get('local'),
                                'prefix': addr.get('prefixlen'),
                                'scope': addr.get('scope')
                            })
                
                interfaces[ifname] = interface_info
                
        except Exception as e:
            print(f"Error getting network interfaces: {e}")
            
        return interfaces
    
    def get_wifi_networks(self) -> List[Dict[str, Any]]:
        """Scan for available WiFi networks"""
        networks = []
        
        try:
            # First, find wireless interfaces
            interfaces = self.get_network_interfaces()
            wifi_interfaces = [name for name, info in interfaces.items() if info['type'] == 'wifi']
            
            if not wifi_interfaces:
                return []
            
            # Use the first WiFi interface for scanning
            wifi_interface = wifi_interfaces[0]
            
            # Check if interface is up
            subprocess.run(["ip", "link", "set", wifi_interface, "up"], capture_output=True)
            
            # Scan using iw command
            result = subprocess.run(
                ["iw", "dev", wifi_interface, "scan"],
                capture_output=True, text=True
            )
            
            if result.returncode == 0:
                # Parse scan results
                current_network = {}
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    
                    if line.startswith('BSS '):
                        # New network found
                        if current_network:
                            networks.append(current_network)
                        current_network = {
                            'bssid': line.split()[1].rstrip('('),
                            'ssid': '',
                            'signal': 0,
                            'security': 'Open',
                            'frequency': 0
                        }
                    elif 'SSID:' in line:
                        current_network['ssid'] = line.split(':', 1)[1].strip()
                    elif 'signal:' in line:
                        # Extract signal strength in dBm
                        match = re.search(r'signal:\s*(-?\d+)', line)
                        if match:
                            dbm = int(match.group(1))
                            # Convert dBm to percentage (rough approximation)
                            current_network['signal'] = max(0, min(100, (dbm + 100) * 2))
                    elif 'freq:' in line:
                        match = re.search(r'freq:\s*(\d+)', line)
                        if match:
                            current_network['frequency'] = int(match.group(1))
                    elif 'RSN:' in line or 'WPA:' in line:
                        current_network['security'] = 'WPA2' if 'RSN:' in line else 'WPA'
                
                # Add last network
                if current_network:
                    networks.append(current_network)
                    
        except subprocess.CalledProcessError as e:
            print(f"WiFi scan error: {e}")
        except FileNotFoundError:
            print("iw command not found. WiFi scanning requires wireless-tools.")
            
        return networks
    
    def get_current_wifi_connection(self) -> Optional[Dict[str, Any]]:
        """Get current WiFi connection info"""
        try:
            # Find wireless interfaces
            interfaces = self.get_network_interfaces()
            
            for name, info in interfaces.items():
                if info['type'] == 'wifi' and info['state'] == 'UP':
                    # Get connection info using iw
                    result = subprocess.run(
                        ["iw", "dev", name, "link"],
                        capture_output=True, text=True
                    )
                    
                    if result.returncode == 0 and 'Connected to' in result.stdout:
                        connection_info = {
                            'interface': name,
                            'ip_addresses': info['ip_addresses']
                        }
                        
                        # Parse connection details
                        for line in result.stdout.split('\n'):
                            if 'SSID:' in line:
                                connection_info['ssid'] = line.split(':', 1)[1].strip()
                            elif 'signal:' in line:
                                match = re.search(r'signal:\s*(-?\d+)', line)
                                if match:
                                    dbm = int(match.group(1))
                                    connection_info['signal'] = max(0, min(100, (dbm + 100) * 2))
                        
                        return connection_info
                        
        except Exception as e:
            print(f"Error getting WiFi connection: {e}")
            
        return None
    
    def read_netplan_config(self) -> Dict[str, Any]:
        """Read current netplan configuration"""
        config = {}
        
        try:
            # Find netplan config files
            config_files = list(self.netplan_dir.glob("*.yaml")) + list(self.netplan_dir.glob("*.yml"))
            
            for config_file in config_files:
                try:
                    with open(config_file, 'r') as f:
                        file_config = yaml.safe_load(f)
                        if file_config:
                            # Merge configurations
                            self._merge_configs(config, file_config)
                except Exception as e:
                    print(f"Error reading {config_file}: {e}")
                    
        except Exception as e:
            print(f"Error reading netplan config: {e}")
            
        return config
    
    def _merge_configs(self, base: Dict, update: Dict):
        """Recursively merge netplan configurations"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_configs(base[key], value)
            else:
                base[key] = value
    
    def update_interface_config(self, interface: str, config: Dict[str, Any]) -> bool:
        """Update network interface configuration in netplan"""
        try:
            # Read current config
            current_config = self.read_netplan_config()
            
            # Ensure network structure exists
            if 'network' not in current_config:
                current_config['network'] = {'version': 2}
            
            network = current_config['network']
            
            # Determine interface type
            interfaces = self.get_network_interfaces()
            if interface not in interfaces:
                raise ValueError(f"Interface {interface} not found")
                
            iface_type = 'ethernets' if interfaces[interface]['type'] == 'ethernet' else 'wifis'
            
            # Ensure interface type section exists
            if iface_type not in network:
                network[iface_type] = {}
            
            # Update interface configuration
            if config.get('method') == 'dhcp':
                network[iface_type][interface] = {
                    'dhcp4': True,
                    'dhcp6': False
                }
            else:  # static
                network[iface_type][interface] = {
                    'dhcp4': False,
                    'dhcp6': False,
                    'addresses': [f"{config['address']}/{config.get('prefix', 24)}"],
                    'gateway4': config.get('gateway'),
                    'nameservers': {
                        'addresses': config.get('dns', [])
                    }
                }
            
            # Write config to a new file
            config_file = self.netplan_dir / "99-uc1-admin.yaml"
            with open(config_file, 'w') as f:
                yaml.dump(current_config, f, default_flow_style=False)
            
            # Apply configuration
            result = subprocess.run(
                ["netplan", "apply"],
                capture_output=True, text=True
            )
            
            return result.returncode == 0
            
        except Exception as e:
            print(f"Error updating interface config: {e}")
            return False
    
    def connect_to_wifi(self, ssid: str, password: str, interface: Optional[str] = None) -> bool:
        """Connect to a WiFi network using netplan"""
        try:
            # Find WiFi interface if not specified
            if not interface:
                interfaces = self.get_network_interfaces()
                wifi_interfaces = [name for name, info in interfaces.items() if info['type'] == 'wifi']
                if not wifi_interfaces:
                    raise ValueError("No WiFi interface found")
                interface = wifi_interfaces[0]
            
            # Read current config
            current_config = self.read_netplan_config()
            
            # Ensure network structure exists
            if 'network' not in current_config:
                current_config['network'] = {'version': 2}
            
            network = current_config['network']
            
            # Ensure wifis section exists
            if 'wifis' not in network:
                network['wifis'] = {}
            
            # Configure WiFi
            network['wifis'][interface] = {
                'dhcp4': True,
                'dhcp6': False,
                'access-points': {
                    ssid: {
                        'password': password
                    }
                }
            }
            
            # Write config
            config_file = self.netplan_dir / "99-uc1-wifi.yaml"
            with open(config_file, 'w') as f:
                yaml.dump(current_config, f, default_flow_style=False)
            
            # Apply configuration
            result = subprocess.run(
                ["netplan", "apply"],
                capture_output=True, text=True
            )
            
            return result.returncode == 0
            
        except Exception as e:
            print(f"Error connecting to WiFi: {e}")
            return False
    
    def disconnect_wifi(self, interface: Optional[str] = None) -> bool:
        """Disconnect from WiFi"""
        try:
            # Find WiFi interface if not specified
            if not interface:
                wifi_conn = self.get_current_wifi_connection()
                if wifi_conn:
                    interface = wifi_conn['interface']
                else:
                    return True  # Already disconnected
            
            # Remove WiFi configuration from netplan
            current_config = self.read_netplan_config()
            
            if ('network' in current_config and 
                'wifis' in current_config['network'] and 
                interface in current_config['network']['wifis']):
                
                del current_config['network']['wifis'][interface]
                
                # Write updated config
                config_file = self.netplan_dir / "99-uc1-wifi.yaml"
                if config_file.exists():
                    config_file.unlink()
                
                # If there are other configs, apply them
                if current_config['network'].get('wifis') or current_config['network'].get('ethernets'):
                    temp_file = self.netplan_dir / "99-uc1-temp.yaml"
                    with open(temp_file, 'w') as f:
                        yaml.dump(current_config, f, default_flow_style=False)
                
                # Apply configuration
                subprocess.run(["netplan", "apply"], capture_output=True)
                
            return True
            
        except Exception as e:
            print(f"Error disconnecting WiFi: {e}")
            return False

# Global instance
network_manager = UbuntuNetworkManager()