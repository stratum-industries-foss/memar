{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    # Python (backend)
    (python311.withPackages (ps: with ps; [
      # FastAPI ecosystem
      fastapi
      uvicorn
      httpx
      # Data & serialization
      pyyaml
      pydantic
      python-multipart
      # Database
      sqlalchemy
      aiosqlite
      # Authentication & cryptography
      passlib
      python-jose
      ldap3          # LDAP SSO (Farm tier)
      pynacl
      cryptography
      bcrypt
      # Billing & email
      stripe
      aiosmtplib
      # WebSocket
      websockets
      # Hardware / IoT — install aiomqtt manually if needed: pip install aiomqtt
      pyserial
    ]))

    # Node.js & npm (frontend + testing)
    nodejs_22

    # Playwright & Chromium
    chromium

    # System libraries for Chromium/Playwright
    libxkbcommon
    libxkbfile
    xorg.libXrandr
    xorg.libX11
    xorg.libxcb
    xorg.libXinerama
    xorg.libXcursor
    xorg.libXi
    xorg.libXxf86vm
    xorg.libXext
    xorg.libXfixes
    xorg.libXdamage
    xorg.libXtst
    at-spi2-atk
    at-spi2-core
    atk
    dbus
    glib
    gtk3
    libxslt
    alsa-lib
    pulseaudio
    libnotify
    libdrm
    libxshmfence
    mesa
    nss
    nspr

    # Build tools
    gcc
    pkg-config
    sqlite
    openssl
    libffi
  ];

  shellHook = ''
    export LD_LIBRARY_PATH=${pkgs.lib.makeLibraryPath [
      pkgs.stdenv.cc.cc pkgs.openssl pkgs.libffi
      pkgs.libxkbcommon pkgs.libxkbfile pkgs.xorg.libXrandr pkgs.xorg.libX11
      pkgs.xorg.libxcb pkgs.xorg.libXinerama pkgs.xorg.libXcursor pkgs.xorg.libXi
      pkgs.xorg.libXxf86vm pkgs.xorg.libXext pkgs.xorg.libXfixes pkgs.xorg.libXdamage
      pkgs.xorg.libXtst pkgs.at-spi2-atk pkgs.at-spi2-core pkgs.atk pkgs.dbus pkgs.glib
      pkgs.gtk3 pkgs.libxslt pkgs.alsa-lib pkgs.pulseaudio pkgs.libappindicator-gtk3
      pkgs.libnotify pkgs.libdrm pkgs.libxshmfence pkgs.mesa pkgs.nss pkgs.nspr
      pkgs.libnghttp2 pkgs.libunistring
    ]}:$LD_LIBRARY_PATH

    # Configure Playwright to use system Chromium
    export PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
    export CHROMIUM_PATH=${pkgs.chromium}/bin/chromium
    export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

    echo "✅ MEMAR dev environment ready"
    echo "   - Python 3.11 with FastAPI deps"
    echo "   - Node.js 22 with npm"
    echo "   - Playwright + system Chromium"
  '';
}
