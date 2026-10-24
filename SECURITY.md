# Security

Report suspected vulnerabilities privately to **[security@unicorncommander.ai](mailto:security@unicorncommander.ai)**. Please avoid public issues for exploitable vulnerabilities.

Include:

- The affected version or commit and component.
- A concise description of the impact and required access.
- Minimal reproduction steps using synthetic data.
- Relevant logs or screenshots with credentials and personal information removed.

Do not send live passwords, tokens, private keys, or customer data. Test only systems you own or are authorized to assess. Coordinate public disclosure with the maintainers while the report is investigated.

Operators should keep runtime configuration private, use HTTPS for sign-in, and restrict access to Docker and host-management features. The Colonel's A2A service credential permits direct tool invocation; its calls do not use the interactive chat approval flow.

See the [README](README.md#configuration) for configuration boundaries and the [legacy local-auth policy](docs/SECURITY_LEGACY_LOCAL_AUTH.md) for authentication context.
