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

# Risk parameters
MAX_POSITION_USDC = 20.0       # max per trade
MIN_EDGE = 0.04                # minimum expected edge (4%)
MAX_OPEN_POSITIONS = 5         # max concurrent positions
MIN_LIQUIDITY_USDC = 500.0     # skip illiquid markets
TARGET_BALANCE_USDC = 1000.0   # goal
STARTING_BALANCE_USDC = 100.0
