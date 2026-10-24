# Contributing to Ops-Center

Start with the [README](README.md#run-from-source) and check [existing issues](https://github.com/Unicorn-Commander/Ops-Center/issues) before opening a new one. For a substantial change, describe the problem and proposed scope in an issue first.

1. Fork the repository and create a focused branch.
2. Make a small, reviewable change that follows the surrounding code.
3. Run the relevant [development checks](README.md#development). For integration or browser tests, use an isolated deployment and disposable accounts; review test defaults before running them.
4. Update documentation when behavior or configuration changes. Include screenshots for interface changes, using synthetic data.
5. Open a pull request explaining the problem, the resulting behavior, and exactly what you tested. Call out migrations, configuration changes, and checks you could not run.

Never commit runtime environment files, credentials, private deployment addresses, or customer data. Report vulnerabilities through [SECURITY.md](SECURITY.md).

The frontend provides Vitest, Playwright, and build commands in [package.json](package.json); there is no frontend lint script. Python linting uses Ruff, installed explicitly as described in the README. Avoid unrelated formatting or dependency changes.

Contributions to Ops-Center are made under the Apache License 2.0, the same licence as the repository (see [LICENSE](LICENSE)). By opening a pull request you confirm you wrote the change or have the right to submit it under that licence.
