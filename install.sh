pip install \
    py-clob-client-v2 \
    py-builder-signing-sdk \
    python-dotenv \
    requests \
    eth-account eth-utils eth-abi

  # Builder relayer needs github main (PyPI 0.0.1 lacks PROXY support)
  pip install --force-reinstall \
    git+https://github.com/Polymarket/py-builder-relayer-client
