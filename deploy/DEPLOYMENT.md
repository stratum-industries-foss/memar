# Deployment

This folder holds production assets:

- `systemd/memar.service`: systemd unit for bare-metal installs (listens on port 9000)
- `systemd/memar.env.example`: template for `/etc/memar.env`

Guides:

- [INSTALL.md](../INSTALL.md): Docker, bare-metal (`scripts/install_systemd_service.sh`), Stripe webhook, and license keys
- [DEPLOYMENT.md](../DEPLOYMENT.md): ports, reverse proxy and TLS, hardening, license generation, troubleshooting
- [docs/OPERATIONS.md](../docs/OPERATIONS.md): backup, restore, upgrade, secret rotation
