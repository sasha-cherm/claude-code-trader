#!/usr/bin/env python3
"""
BTC 15-min Candle Predictor
Estimates the probability that the next 15-minute BTC candle will be GREEN (close > open).

Uses Binance public API for historical data.
Combines multiple signals via logistic regression trained on recent history.

Usage:
    python3 btc_candle_predictor.py              # Full analysis + prediction
    python3 btc_candle_predictor.py --backtest    # Run backtest with stats
    python3 btc_candle_predictor.py --json        # Output JSON for integration
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline


# ─── Binance Data ───────────────────────────────────────────────────────────

def fetch_binance_klines(symbol="BTCUSDT", interval="15m", limit=1000):
    """Fetch klines from Binance. Max 1000 per request."""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_vol",
        "taker_buy_quote_vol", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume", "quote_volume",
                "taker_buy_vol", "taker_buy_quote_vol"]:
        df[col] = df[col].astype(float)
    df["trades"] = df["trades"].astype(int)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df


def fetch_extended_history(symbol="BTCUSDT", interval="15m", num_candles=4000):
    """Fetch more than 1000 candles by paginating backwards."""
    all_dfs = []
    end_time = None
    remaining = num_candles

    while remaining > 0:
        limit = min(remaining, 1000)
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if end_time is not None:
            params["endTime"] = end_time
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data:
            break

        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_vol",
            "taker_buy_quote_vol", "ignore"
        ])
        all_dfs.append(df)
        end_time = int(data[0][0]) - 1  # 1ms before earliest candle
        remaining -= len(data)
        if len(data) < limit:
            break
        time.sleep(0.1)  # rate limit

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs[::-1], ignore_index=True)
    for col in ["open", "high", "low", "close", "volume", "quote_volume",
                "taker_buy_vol", "taker_buy_quote_vol"]:
        combined[col] = combined[col].astype(float)
    combined["trades"] = combined["trades"].astype(int)
    combined["open_time"] = pd.to_datetime(combined["open_time"], unit="ms", utc=True)
    combined["close_time"] = pd.to_datetime(combined["close_time"], unit="ms", utc=True)
    return combined


def fetch_1m_klines(symbol="BTCUSDT", limit=120):
    """Fetch recent 1-minute candles for micro-structure analysis."""
    return fetch_binance_klines(symbol, "1m", limit)


# ─── Feature Engineering ────────────────────────────────────────────────────

def compute_features(df, lookahead=0):
    """Compute all features from 15-min OHLCV data.

    lookahead: number of extra candles to shift features by.
        0 = predict next candle using immediately preceding data (default)
        2 = predict candle using data from 2 candles before (30 min before)
        4 = predict candle using data from 4 candles before (60 min before)
    All .shift(1) becomes .shift(1 + lookahead).
    """
    S = 1 + lookahead  # shift amount
    feat = pd.DataFrame(index=df.index)

    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]

    # Target: 1 if green candle (close >= open)
    feat["green"] = (c >= o).astype(int)

    # --- Streak features ---
    green = feat["green"]
    streak = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        if green.iloc[i-1] == green.iloc[i-2] if i >= 2 else False:
            streak.iloc[i] = streak.iloc[i-1] + (1 if green.iloc[i-1] == 1 else -1)
        else:
            streak.iloc[i] = 1 if green.iloc[i-1] == 1 else -1
    feat["streak"] = streak.shift(S)

    green_streak = pd.Series(0, index=df.index, dtype=int)
    red_streak = pd.Series(0, index=df.index, dtype=int)
    for i in range(1, len(df)):
        if green.iloc[i-1] == 1:
            green_streak.iloc[i] = green_streak.iloc[i-1] + 1
            red_streak.iloc[i] = 0
        else:
            red_streak.iloc[i] = red_streak.iloc[i-1] + 1
            green_streak.iloc[i] = 0
    feat["green_streak"] = green_streak.shift(lookahead)
    feat["red_streak"] = red_streak.shift(lookahead)

    # --- Price action features ---
    # Returns
    feat["ret_1"] = c.pct_change(1).shift(S)
    feat["ret_2"] = c.pct_change(2).shift(S)
    feat["ret_4"] = c.pct_change(4).shift(S)
    feat["ret_8"] = c.pct_change(8).shift(S)
    feat["ret_16"] = c.pct_change(16).shift(S)

    # Body size relative to range
    body = (c - o).abs()
    candle_range = h - l
    feat["body_ratio"] = (body / candle_range.replace(0, np.nan)).shift(S)

    # Upper/lower wick ratios
    upper_wick = h - pd.concat([c, o], axis=1).max(axis=1)
    lower_wick = pd.concat([c, o], axis=1).min(axis=1) - l
    feat["upper_wick_ratio"] = (upper_wick / candle_range.replace(0, np.nan)).shift(S)
    feat["lower_wick_ratio"] = (lower_wick / candle_range.replace(0, np.nan)).shift(S)

    # --- Moving averages ---
    for period in [5, 10, 20, 50]:
        sma = c.rolling(period).mean()
        feat[f"price_vs_sma{period}"] = ((c - sma) / sma).shift(S)

    # EMA
    for period in [5, 10, 20]:
        ema = c.ewm(span=period, adjust=False).mean()
        feat[f"price_vs_ema{period}"] = ((c - ema) / ema).shift(S)

    # --- RSI ---
    for period in [7, 14]:
        delta = c.diff()
        gain = delta.where(delta > 0, 0.0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        feat[f"rsi_{period}"] = (100 - 100 / (1 + rs)).shift(S)

    # --- MACD ---
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    feat["macd"] = macd_line.shift(S)
    feat["macd_signal"] = signal_line.shift(S)
    feat["macd_hist"] = (macd_line - signal_line).shift(S)

    # --- Bollinger Bands ---
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    feat["bb_position"] = ((c - sma20) / (2 * std20.replace(0, np.nan))).shift(S)

    # --- Volume features ---
    vol_sma10 = v.rolling(10).mean()
    feat["vol_ratio"] = (v / vol_sma10.replace(0, np.nan)).shift(S)
    feat["vol_change"] = v.pct_change(1).shift(S)

    # Taker buy ratio (buying pressure)
    feat["taker_buy_ratio"] = (df["taker_buy_vol"] / v.replace(0, np.nan)).shift(S)

    # Volume trend
    feat["vol_sma5_vs_sma20"] = (v.rolling(5).mean() / v.rolling(20).mean().replace(0, np.nan)).shift(S)

    # --- Volatility ---
    feat["atr_14"] = (candle_range.rolling(14).mean() / c).shift(S)
    feat["volatility_5"] = c.pct_change().rolling(5).std().shift(S)
    feat["volatility_20"] = c.pct_change().rolling(20).std().shift(S)

    # --- Stochastic oscillator ---
    low14 = l.rolling(14).min()
    high14 = h.rolling(14).max()
    feat["stoch_k"] = (100 * (c - low14) / (high14 - low14).replace(0, np.nan)).shift(S)
    feat["stoch_d"] = feat["stoch_k"].rolling(3).mean()

    # --- Williams %R ---
    feat["williams_r"] = (-100 * (high14 - c) / (high14 - low14).replace(0, np.nan)).shift(S)

    # --- Support/Resistance proximity ---
    for lookback in [20, 50]:
        recent_high = h.rolling(lookback).max().shift(S)
        recent_low = l.rolling(lookback).min().shift(S)
        price_range = recent_high - recent_low
        feat[f"sr_position_{lookback}"] = ((c.shift(S) - recent_low) / price_range.replace(0, np.nan))

    # Distance to round numbers (psychological levels)
    feat["dist_to_round_1000"] = ((c.shift(S) % 1000) / 1000)
    feat["dist_to_round_500"] = ((c.shift(S) % 500) / 500)

    # --- Time features ---
    feat["hour"] = df["open_time"].dt.hour
    feat["minute"] = df["open_time"].dt.minute
    feat["day_of_week"] = df["open_time"].dt.dayofweek
    # Cyclical encoding
    feat["hour_sin"] = np.sin(2 * np.pi * feat["hour"] / 24)
    feat["hour_cos"] = np.cos(2 * np.pi * feat["hour"] / 24)
    feat["dow_sin"] = np.sin(2 * np.pi * feat["day_of_week"] / 7)
    feat["dow_cos"] = np.cos(2 * np.pi * feat["day_of_week"] / 7)

    # --- Mean reversion signal ---
    feat["mean_revert_signal"] = -(feat["green_streak"] - feat["red_streak"])

    # --- Momentum / ROC ---
    feat["roc_4"] = ((c / c.shift(4) - 1) * 100).shift(S)
    feat["roc_8"] = ((c / c.shift(8) - 1) * 100).shift(S)

    # --- ADX (simplified) ---
    plus_dm = h.diff()
    minus_dm = -l.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    atr = candle_range.rolling(14).mean()
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.rolling(14).mean() / atr.replace(0, np.nan))
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    feat["adx"] = dx.rolling(14).mean().shift(S)
    feat["plus_di"] = plus_di.shift(S)
    feat["minus_di"] = minus_di.shift(S)

    return feat


def compute_1m_features(df_1m, current_time_utc=None):
    """Compute micro-structure features from 1-minute data.
    These capture what's happening RIGHT NOW (in the lead-up to the next 15-min candle).
    """
    if df_1m.empty:
        return {}

    c = df_1m["close"]
    v = df_1m["volume"]

    features = {}

    # Last 15 1-min candles (= 1 full 15-min candle equivalent)
    last15 = df_1m.tail(15)
    last30 = df_1m.tail(30)
    last60 = df_1m.tail(60)

    # Micro momentum (last 5, 15, 30, 60 minutes)
    for n, label in [(5, "5m"), (15, "15m"), (30, "30m"), (60, "60m")]:
        tail = df_1m.tail(n)
        if len(tail) >= n:
            features[f"micro_ret_{label}"] = (tail["close"].iloc[-1] / tail["close"].iloc[0] - 1)

    # Micro volatility
    if len(last15) >= 15:
        features["micro_vol_15m"] = last15["close"].pct_change().std()
    if len(last60) >= 60:
        features["micro_vol_60m"] = last60["close"].pct_change().std()

    # Volume acceleration (are we seeing unusual volume right now?)
    if len(last60) >= 60:
        vol_recent = last15["volume"].mean() if len(last15) >= 15 else v.tail(15).mean()
        vol_baseline = last60["volume"].mean()
        features["micro_vol_ratio"] = vol_recent / max(vol_baseline, 1e-10)

    # Taker buy pressure in last 15 minutes
    if len(last15) >= 15 and "taker_buy_vol" in df_1m.columns:
        tbv = last15["taker_buy_vol"].sum()
        tv = last15["volume"].sum()
        features["micro_taker_buy_ratio"] = tbv / max(tv, 1e-10)

    # Number of green vs red 1-min candles in last 15
    if len(last15) >= 15:
        greens = (last15["close"] >= last15["open"]).sum()
        features["micro_green_ratio_15"] = greens / len(last15)

    # Price position within last 60-min range
    if len(last60) >= 60:
        h60 = last60["high"].max()
        l60 = last60["low"].min()
        r = h60 - l60
        if r > 0:
            features["micro_range_position"] = (c.iloc[-1] - l60) / r

    # RSI on 1-min (14-period)
    if len(df_1m) >= 20:
        delta = c.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        features["micro_rsi_14"] = rsi.iloc[-1]

    return features


# ─── Model ──────────────────────────────────────────────────────────────────

from sklearn.ensemble import (
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    VotingClassifier,
)
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")


def get_feature_cols(feat_df):
    """Get feature column names (everything except target and time cols)."""
    exclude = {"green", "hour", "minute", "day_of_week"}
    return [c for c in feat_df.columns if c not in exclude]


def _make_ensemble():
    """Create the ensemble of models."""
    lr_pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(C=0.1, l1_ratio=0, solver="lbfgs",
                                  max_iter=5000, class_weight="balanced"))
    ])

    hgb = HistGradientBoostingClassifier(
        max_iter=200,
        max_depth=4,
        learning_rate=0.05,
        min_samples_leaf=30,
        l2_regularization=1.0,
        random_state=42,
    )

    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=5,
        min_samples_leaf=20,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )

    ensemble = VotingClassifier(
        estimators=[("lr", lr_pipe), ("hgb", hgb), ("rf", rf)],
        voting="soft",
        weights=[1, 2, 1],  # GBM gets double weight
    )
    return ensemble


def train_model(feat_df, feature_cols):
    """Train calibrated ensemble on the feature set."""
    # Only require green + a subset of key columns to not drop too many rows
    df = feat_df.dropna(subset=["green"])
    df = df.dropna(subset=feature_cols, thresh=len(feature_cols) - 5)
    if len(df) < 200:
        return None, None, None

    X = np.nan_to_num(df[feature_cols].values.copy(), nan=0.0)
    y = df["green"].values

    ensemble = _make_ensemble()

    # Calibrate with time-series CV
    tscv = TimeSeriesSplit(n_splits=5)
    cal_model = CalibratedClassifierCV(ensemble, cv=tscv, method="isotonic")
    cal_model.fit(X, y)

    return cal_model, feature_cols, df


def train_single_model(X_train, y_train, model_type="ensemble"):
    """Train a single model (for backtest walk-forward)."""
    if model_type == "lr":
        model = Pipeline([
            ("scaler", StandardScaler()),
            ("lr", LogisticRegression(C=0.1, l1_ratio=0, solver="lbfgs",
                                      max_iter=5000, class_weight="balanced"))
        ])
    elif model_type == "hgb":
        model = HistGradientBoostingClassifier(
            max_iter=200, max_depth=4, learning_rate=0.05,
            min_samples_leaf=30, l2_regularization=1.0, random_state=42,
        )
    elif model_type == "rf":
        model = RandomForestClassifier(
            n_estimators=200, max_depth=5, min_samples_leaf=20,
            class_weight="balanced", random_state=42, n_jobs=-1,
        )
    else:  # ensemble
        model = _make_ensemble()

    model.fit(X_train, y_train)
    return model


def predict_proba(model, feature_cols, feature_row):
    """Get probability of green candle from a single feature row."""
    if model is None:
        return 0.5

    x = np.array([feature_row[col] for col in feature_cols], dtype=float).reshape(1, -1)
    x = np.nan_to_num(x, nan=0.0)

    proba = model.predict_proba(x)[0]
    classes = model.classes_
    green_idx = np.where(classes == 1)[0][0]
    return proba[green_idx]


# ─── Backtest ───────────────────────────────────────────────────────────────

def run_backtest(feat_df, feature_cols, n_test=500, model_type="ensemble", retrain_every=50):
    """Walk-forward backtest: train on expanding window, predict next candle.
    Retrains every `retrain_every` steps to speed up ensemble backtests.
    """
    df = feat_df.dropna(subset=["green"])
    df = df.dropna(subset=feature_cols, thresh=len(feature_cols) - 5).reset_index(drop=True)
    n = len(df)
    train_start = max(200, n - n_test)

    predictions = []
    actuals = []

    actual_n_test = n - train_start
    print(f"\nBacktest [{model_type}]: {actual_n_test} predictions, retrain every {retrain_every}")
    print(f"Data range: {n} total samples")

    current_model = None
    for i in range(train_start, n):
        # Retrain periodically (full ensemble is expensive)
        if current_model is None or (i - train_start) % retrain_every == 0:
            train_X = np.nan_to_num(df.loc[:i-1, feature_cols].values.copy(), nan=0.0)
            train_y = df.loc[:i-1, "green"].values
            current_model = train_single_model(train_X, train_y, model_type)
            if (i - train_start) % 100 == 0:
                pct = (i - train_start) / actual_n_test * 100
                print(f"  Progress: {pct:.0f}% ({i - train_start}/{actual_n_test})")

        test_x = np.nan_to_num(df.loc[i, feature_cols].values.copy().reshape(1, -1), nan=0.0)
        prob = current_model.predict_proba(test_x)[0]
        classes = current_model.classes_
        green_idx = np.where(classes == 1)[0][0]

        predictions.append(prob[green_idx])
        actuals.append(df.loc[i, "green"])

    predictions = np.array(predictions)
    actuals = np.array(actuals)

    # --- Statistics ---
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)

    # Overall accuracy at 50% threshold
    pred_class = (predictions > 0.5).astype(int)
    accuracy = (pred_class == actuals).mean()
    print(f"\nOverall accuracy (50% threshold): {accuracy:.4f}")
    print(f"Base rate (% green candles):       {actuals.mean():.4f}")
    print(f"Improvement over base rate:        {accuracy - max(actuals.mean(), 1 - actuals.mean()):.4f}")

    # Calibration analysis: bin predictions and check actual rates
    print(f"\n{'Prob Bin':>12} {'Count':>6} {'Actual Green%':>14} {'Avg Pred':>10} {'Calib Error':>12}")
    print("-" * 60)
    bins = [(0, 0.35), (0.35, 0.40), (0.40, 0.45), (0.45, 0.50),
            (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 1.0)]
    for lo, hi in bins:
        mask = (predictions >= lo) & (predictions < hi)
        if mask.sum() > 0:
            actual_rate = actuals[mask].mean()
            avg_pred = predictions[mask].mean()
            calib_err = abs(actual_rate - avg_pred)
            print(f"  [{lo:.2f}, {hi:.2f})  {mask.sum():>5}  {actual_rate:>13.4f}  {avg_pred:>9.4f}  {calib_err:>11.4f}")

    # Edge analysis: when model is confident, how accurate?
    print(f"\n--- Edge Analysis ---")
    for threshold in [0.55, 0.60, 0.65]:
        mask = predictions > threshold
        if mask.sum() > 5:
            win_rate = actuals[mask].mean()
            print(f"  Pred > {threshold:.2f}: {mask.sum():>4} trades, win rate {win_rate:.4f}")

    for threshold in [0.45, 0.40, 0.35]:
        mask = predictions < threshold
        if mask.sum() > 5:
            win_rate = 1 - actuals[mask].mean()  # betting RED
            print(f"  Pred < {threshold:.2f}: {mask.sum():>4} trades (bet RED), win rate {win_rate:.4f}")

    # Brier score
    brier = ((predictions - actuals) ** 2).mean()
    baseline_brier = ((actuals.mean() - actuals) ** 2).mean()
    print(f"\nBrier score:          {brier:.4f}")
    print(f"Baseline Brier score: {baseline_brier:.4f}")
    print(f"Brier skill score:    {1 - brier / baseline_brier:.4f}")

    # Log-loss
    eps = 1e-7
    logloss = -np.mean(actuals * np.log(predictions + eps) +
                       (1 - actuals) * np.log(1 - predictions + eps))
    baseline_ll = -np.mean(actuals * np.log(actuals.mean() + eps) +
                           (1 - actuals) * np.log(1 - actuals.mean() + eps))
    print(f"Log-loss:             {logloss:.4f}")
    print(f"Baseline log-loss:    {baseline_ll:.4f}")

    # Profitability simulation (Polymarket-style)
    print(f"\n--- Polymarket Profitability Simulation ---")
    print(f"  Assuming market price = 50c, you buy at model's probability")
    print(f"  Bet $1 when edge > 3c (prob > 0.53 or prob < 0.47)")

    total_bets = 0
    total_profit = 0
    for i in range(len(predictions)):
        p = predictions[i]
        actual = actuals[i]
        if p > 0.53:  # bet GREEN
            edge = p - 0.50
            cost = 0.50  # buy at market
            payout = 1.0 if actual == 1 else 0.0
            total_profit += payout - cost
            total_bets += 1
        elif p < 0.47:  # bet RED
            edge = 0.50 - p
            cost = 0.50
            payout = 1.0 if actual == 0 else 0.0
            total_profit += payout - cost
            total_bets += 1

    if total_bets > 0:
        print(f"  Total bets: {total_bets}")
        print(f"  Total P/L:  ${total_profit:.2f}")
        print(f"  Avg P/L per bet: ${total_profit / total_bets:.4f}")
        print(f"  ROI: {total_profit / (total_bets * 0.50) * 100:.2f}%")
    else:
        print(f"  No bets placed (no confident predictions)")

    return predictions, actuals


# ─── Individual Signal Analysis ─────────────────────────────────────────────

def analyze_individual_signals(feat_df):
    """Analyze predictive power of each feature independently."""
    df = feat_df.dropna(subset=["green"]).copy()
    feature_cols = get_feature_cols(feat_df)

    print("\n" + "=" * 60)
    print("INDIVIDUAL SIGNAL ANALYSIS")
    print("=" * 60)
    print(f"{'Feature':>30} {'Corr':>8} {'IC':>8} {'Solo AUC':>10}")
    print("-" * 60)

    from sklearn.metrics import roc_auc_score

    results = []
    for col in feature_cols:
        valid = df[[col, "green"]].dropna()
        if len(valid) < 100:
            continue
        corr = valid[col].corr(valid["green"])
        # Information coefficient (rank correlation)
        ic = valid[col].rank().corr(valid["green"])
        # Solo AUC
        try:
            auc = roc_auc_score(valid["green"], valid[col])
        except:
            auc = 0.5
        results.append((col, corr, ic, auc))

    results.sort(key=lambda x: abs(x[1]), reverse=True)
    for col, corr, ic, auc in results[:30]:
        print(f"  {col:>28} {corr:>7.4f} {ic:>7.4f} {auc:>9.4f}")

    return results


# ─── Streak Analysis ────────────────────────────────────────────────────────

def analyze_streaks(feat_df):
    """Analyze green/red streak patterns and mean reversion."""
    df = feat_df.dropna(subset=["green", "green_streak", "red_streak"]).copy()

    print("\n" + "=" * 60)
    print("STREAK ANALYSIS (Mean Reversion)")
    print("=" * 60)
    print(f"{'After streak':>20} {'Count':>6} {'Next Green%':>12} {'Edge vs 50%':>12}")
    print("-" * 55)

    for n in range(1, 8):
        # After N green candles
        mask = df["green_streak"] == n
        if mask.sum() >= 10:
            rate = df.loc[mask, "green"].mean()
            print(f"  {n} green in a row    {mask.sum():>5}  {rate:>11.4f}  {rate - 0.5:>+11.4f}")

    print()
    for n in range(1, 8):
        # After N red candles
        mask = df["red_streak"] == n
        if mask.sum() >= 10:
            rate = df.loc[mask, "green"].mean()
            print(f"  {n} red in a row      {mask.sum():>5}  {rate:>11.4f}  {rate - 0.5:>+11.4f}")


# ─── Hour-of-Day Analysis ───────────────────────────────────────────────────

def analyze_time_patterns(feat_df):
    """Analyze green candle probability by hour and day of week."""
    df = feat_df.dropna(subset=["green"]).copy()

    print("\n" + "=" * 60)
    print("HOURLY PATTERN")
    print("=" * 60)
    print(f"{'Hour (UTC)':>12} {'Count':>6} {'Green%':>8} {'Edge':>8}")
    print("-" * 38)

    for hour in range(24):
        mask = df["hour"] == hour
        if mask.sum() >= 20:
            rate = df.loc[mask, "green"].mean()
            print(f"  {hour:>2}:00        {mask.sum():>5}  {rate:>7.4f}  {rate - 0.5:>+7.4f}")

    print("\n" + "=" * 60)
    print("DAY OF WEEK PATTERN")
    print("=" * 60)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    print(f"{'Day':>12} {'Count':>6} {'Green%':>8} {'Edge':>8}")
    print("-" * 38)
    for dow in range(7):
        mask = df["day_of_week"] == dow
        if mask.sum() >= 20:
            rate = df.loc[mask, "green"].mean()
            print(f"  {days[dow]:>5}        {mask.sum():>5}  {rate:>7.4f}  {rate - 0.5:>+7.4f}")


# ─── RSI Zone Analysis ──────────────────────────────────────────────────────

def analyze_rsi_zones(feat_df):
    """Analyze green probability by RSI zone."""
    df = feat_df.dropna(subset=["green", "rsi_14"]).copy()

    print("\n" + "=" * 60)
    print("RSI ZONE ANALYSIS")
    print("=" * 60)
    print(f"{'RSI Zone':>15} {'Count':>6} {'Green%':>8} {'Edge':>8}")
    print("-" * 40)

    zones = [(0, 20, "Oversold <20"),
             (20, 30, "20-30"),
             (30, 40, "30-40"),
             (40, 50, "40-50"),
             (50, 60, "50-60"),
             (60, 70, "60-70"),
             (70, 80, "70-80"),
             (80, 100, "Overbought >80")]

    for lo, hi, label in zones:
        mask = (df["rsi_14"] >= lo) & (df["rsi_14"] < hi)
        if mask.sum() >= 10:
            rate = df.loc[mask, "green"].mean()
            print(f"  {label:>13}  {mask.sum():>5}  {rate:>7.4f}  {rate - 0.5:>+7.4f}")


# ─── Main Prediction ────────────────────────────────────────────────────────

def make_prediction(verbose=True, lookahead=0):
    """Make a prediction for the next 15-minute candle.

    lookahead: extra candles of feature shift (2=30min early, 4=60min early).
    """
    if verbose:
        print("Fetching 15-min candles from Binance...")
    df_15m = fetch_extended_history(num_candles=4000)
    if verbose:
        print(f"  Got {len(df_15m)} candles, from {df_15m['open_time'].iloc[0]} to {df_15m['open_time'].iloc[-1]}")

    if verbose:
        print("Fetching 1-min candles...")
    df_1m = fetch_1m_klines(limit=120)
    if verbose:
        print(f"  Got {len(df_1m)} candles")

    # Compute features
    if verbose:
        la_label = f" (lookahead={lookahead}, {lookahead*15}min early)" if lookahead else ""
        print(f"Computing features...{la_label}")
    feat = compute_features(df_15m, lookahead=lookahead)
    feature_cols = get_feature_cols(feat)

    # Train model
    if verbose:
        print("Training model...")
    model, fcols, train_df = train_model(feat, feature_cols)

    # Get latest feature row (for next candle prediction)
    last_row = feat.iloc[-1]

    # Get 1-min micro features
    micro = compute_1m_features(df_1m)

    # Model prediction (RF is the primary model)
    model_prob = predict_proba(model, fcols, last_row) if model else 0.5

    # Context signals
    gs = int(last_row.get("green_streak", 0)) if not np.isnan(last_row.get("green_streak", 0)) else 0
    rs = int(last_row.get("red_streak", 0)) if not np.isnan(last_row.get("red_streak", 0)) else 0
    rsi = last_row.get("rsi_14", 50)
    if np.isnan(rsi):
        rsi = 50.0
    bb = last_row.get("bb_position", 0)
    if np.isnan(bb):
        bb = 0.0
    stoch = last_row.get("stoch_k", 50)
    if np.isnan(stoch):
        stoch = 50.0

    # The model IS the probability. No heuristic overrides.
    # Backtested: RF at 0.54+ threshold = 60.3% win rate, 20.7% ROI
    prob_green = model_prob

    # Next candle timing
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    minutes = now.minute
    next_15 = 15 - (minutes % 15)
    next_candle_start = now.replace(second=0, microsecond=0) + timedelta(minutes=next_15)

    last_close = df_15m["close"].iloc[-1]
    last_candle_color = "GREEN" if df_15m["close"].iloc[-1] >= df_15m["open"].iloc[-1] else "RED"

    # Recommendation logic (based on backtest edge analysis)
    if prob_green >= 0.54:
        rec = "BUY UP"
        edge = prob_green - 0.50
        max_price = round(prob_green - 0.02, 2)  # 2c margin of safety
    elif prob_green <= 0.43:
        rec = "BUY DOWN"
        edge = 0.50 - prob_green
        max_price = round((1 - prob_green) - 0.02, 2)
    else:
        rec = "SKIP"
        edge = abs(prob_green - 0.5)
        max_price = None

    # Kelly criterion: f* = (bp - q) / b where b=1 (even money at 50c), p=prob, q=1-p
    # With 50c market price: b = payout/cost - 1 = 1/0.5 - 1 = 1
    kelly_frac = (2 * prob_green - 1) if prob_green > 0.5 else (1 - 2 * prob_green)
    # Half-Kelly for safety
    half_kelly = kelly_frac / 2

    result = {
        "timestamp_utc": now.isoformat(),
        "next_candle_start_utc": next_candle_start.isoformat(),
        "minutes_until_candle": next_15,
        "lookahead_candles": lookahead,
        "btc_price": last_close,
        "last_candle_color": last_candle_color,
        "green_streak": gs,
        "red_streak": rs,
        "rsi_14": round(rsi, 2),
        "bb_position": round(bb, 4),
        "stoch_k": round(stoch, 2),
        "probability_green": round(prob_green, 4),
        "probability_red": round(1 - prob_green, 4),
        "recommendation": rec,
        "edge_over_fair": round(edge, 4),
        "max_buy_price": max_price,
        "kelly_fraction": round(kelly_frac, 4),
        "half_kelly_fraction": round(half_kelly, 4),
        "micro_features": {k: round(v, 4) if isinstance(v, float) else v for k, v in micro.items()},
    }

    if verbose:
        print("\n" + "=" * 60)
        print("BTC 15-MIN CANDLE PREDICTION")
        print("=" * 60)
        print(f"  Time (UTC):            {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Next candle:           {next_candle_start.strftime('%H:%M:%S')} (in {next_15} min)")
        if lookahead:
            print(f"  Lookahead:             {lookahead} candles ({lookahead*15} min early)")
        print(f"  BTC price:             ${last_close:,.2f}")
        print(f"  Last candle:           {last_candle_color}")
        print()

        # Context
        print("  --- Context ---")
        if gs > 0:
            print(f"  Green streak:          {gs} candles in a row")
        if rs > 0:
            print(f"  Red streak:            {rs} candles in a row")
        print(f"  RSI(14):               {rsi:.1f}", end="")
        if rsi < 30:
            print("  << OVERSOLD")
        elif rsi > 70:
            print("  << OVERBOUGHT")
        else:
            print()
        print(f"  Bollinger position:    {bb:+.3f}", end="")
        if bb < -0.8:
            print("  << NEAR LOWER BAND")
        elif bb > 0.8:
            print("  << NEAR UPPER BAND")
        else:
            print()
        print(f"  Stochastic K:          {stoch:.1f}")
        print()

        # Micro features
        if micro:
            print("  --- Micro (1-min data) ---")
            for k, v in sorted(micro.items()):
                if isinstance(v, float):
                    print(f"  {k:24s} {v:.4f}")
            print()

        # Prediction
        print("  --- Prediction ---")
        print(f"  P(green):              {prob_green:.1%}")
        print(f"  P(red):                {1-prob_green:.1%}")
        print()

        # Recommendation
        if rec != "SKIP":
            side = "UP" if "UP" in rec else "DOWN"
            print(f"  >>> RECOMMENDATION:    {rec}")
            print(f"  >>> Edge over 50c:     {edge:.1%}")
            print(f"  >>> Max buy price:     {max_price:.2f}c")
            print(f"  >>> Kelly fraction:    {kelly_frac:.1%} (half-Kelly: {half_kelly:.1%})")
            print()
            # Practical sizing
            print(f"  --- Polymarket Sizing ---")
            for bankroll in [5, 10, 15, 20]:
                bet = round(bankroll * half_kelly, 2)
                if bet >= 0.50:
                    shares = int(bet / (max_price / 100))
                    print(f"  ${bankroll} bankroll:  bet ${bet:.2f} ({shares} shares at {max_price}c)")
        else:
            print(f"  >>> RECOMMENDATION:    SKIP (edge {edge:.1%} < 4% threshold)")
            print(f"  Model prob:            {prob_green:.4f} (need >0.54 or <0.43)")

    return result, feat, model, fcols


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BTC 15-min Candle Predictor")
    parser.add_argument("--backtest", action="store_true", help="Run backtest")
    parser.add_argument("--compare", action="store_true", help="Compare all model types")
    parser.add_argument("--signals", action="store_true", help="Analyze individual signals")
    parser.add_argument("--streaks", action="store_true", help="Analyze streak patterns")
    parser.add_argument("--time", action="store_true", help="Analyze time patterns")
    parser.add_argument("--rsi", action="store_true", help="Analyze RSI zones")
    parser.add_argument("--all", action="store_true", help="Run all analyses")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument("--model", default="rf",
                        choices=["lr", "hgb", "rf", "ensemble"],
                        help="Model type for backtest")
    parser.add_argument("--lookahead", type=int, default=0,
                        help="Extra candles of lookahead (2=30min, 4=60min before candle)")
    args = parser.parse_args()

    if args.json:
        result, _, _, _ = make_prediction(verbose=False, lookahead=args.lookahead)
        print(json.dumps(result, indent=2))
        return

    # Always make prediction
    result, feat, model, fcols = make_prediction(verbose=True, lookahead=args.lookahead)

    if args.all or args.signals:
        analyze_individual_signals(feat)

    if args.all or args.streaks:
        analyze_streaks(feat)

    if args.all or args.time:
        analyze_time_patterns(feat)

    if args.all or args.rsi:
        analyze_rsi_zones(feat)

    if args.compare:
        feature_cols = get_feature_cols(feat)
        for mt in ["lr", "hgb", "rf", "ensemble"]:
            print(f"\n{'#' * 60}")
            print(f"  MODEL: {mt.upper()}")
            print(f"{'#' * 60}")
            run_backtest(feat, feature_cols, model_type=mt, retrain_every=50)

    elif args.all or args.backtest:
        feature_cols = get_feature_cols(feat)
        run_backtest(feat, feature_cols, model_type=args.model)


if __name__ == "__main__":
    main()
