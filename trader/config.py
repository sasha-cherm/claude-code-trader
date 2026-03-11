"""Load configuration from .env file."""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

PRIVATE_KEY: str = os.environ["POLYMARKET_PRIVATE_KEY"]
PROXY_ADDRESS: str = os.getenv("POLYMARKET_PROXY_ADDRESS", "")  # proxy wallet (where funds live)
CHAIN_ID: int = int(os.getenv("CHAIN_ID", "137"))  # Polygon mainnet
CLOB_HOST: str = os.getenv("CLOB_HOST", "https://clob.polymarket.com")
GAMMA_HOST: str = os.getenv("GAMMA_HOST", "https://gamma-api.polymarket.com")

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# Risk parameters — aggressive sizing for 10x goal
MAX_POSITION_PCT = 0.20        # max 20% of bankroll per trade (was 15%)
MIN_POSITION_USDC = 5.0        # minimum bet size (was 3.0)
MAX_POSITION_USDC = 80.0       # hard cap per trade (was 50)
MIN_EDGE = 0.04                # minimum expected edge (4%)
MAX_OPEN_POSITIONS = 8         # max concurrent positions (raised for capital deployment)
MIN_LIQUIDITY_USDC = 500.0     # skip illiquid markets
TARGET_BALANCE_USDC = 1000.0   # goal
STARTING_BALANCE_USDC = 100.0
