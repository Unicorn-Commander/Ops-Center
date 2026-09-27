const configuredKeycloakBaseUrl = import.meta.env.VITE_KEYCLOAK_EXTERNAL_URL;
const keycloakRealm = import.meta.env.VITE_KEYCLOAK_REALM || 'uchub';

export const getKeycloakBaseUrl = () => {
  if (configuredKeycloakBaseUrl) {
    return configuredKeycloakBaseUrl.replace(/\/+$/, '');
  }

  if (typeof window === 'undefined') {
    return '';
  }

  return `${window.location.protocol}//auth.${window.location.hostname}`;
};

export const getKeycloakAccountSignInUrl = () =>
  `${getKeycloakBaseUrl()}/realms/${keycloakRealm}/account/#/security/signingin`;
