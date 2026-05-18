import pandas as pd
import numpy as np
import logging
from data import get_h1_data, get_m5_data

logger = logging.getLogger(__name__)


# ─── Core indicators ──────────────────────────────────────────────────────────

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_atr(df, period=14):
    high = df['High']
    low = df['Low']
    close = df['Close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ─── H1 trend ─────────────────────────────────────────────────────────────────

def analyze_trend(h1_df):
    close = h1_df['Close']
    ema21 = calc_ema(close, 21)
    ema50 = calc_ema(close, 50)
    ema200 = calc_ema(close, 200)
    e21 = float(ema21.iloc[-1])
    e50 = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])
    price = float(close.iloc[-1])

    if e21 > e50 > e200 and price > e200:
        return 'bullish', e21, e50, e200
    elif e21 < e50 < e200 and price < e200:
        return 'bearish', e21, e50, e200
    return 'neutral', e21, e50, e200


# ─── FVG detection ────────────────────────────────────────────────────────────

def detect_fvg(df, direction):
    fvgs = []
    for i in range(2, len(df)):
        c1 = df.iloc[i - 2]
        c3 = df.iloc[i]
        if direction == 'bullish' and float(c1['High']) < float(c3['Low']):
            fvgs.append({'top': float(c3['Low']), 'bottom': float(c1['High']), 'index': i, 'type': 'bullish'})
        elif direction == 'bearish' and float(c1['Low']) > float(c3['High']):
            fvgs.append({'top': float(c1['Low']), 'bottom': float(c3['High']), 'index': i, 'type': 'bearish'})
    return fvgs


# ─── Order block detection ────────────────────────────────────────────────────

def detect_order_blocks(df, direction):
    obs = []
    bodies = (df['Close'] - df['Open']).abs()
    avg_body = float(bodies.mean())
    for i in range(1, len(df) - 2):
        c = df.iloc[i]
        nxt = df.iloc[i + 1]
        next_body = float(abs(float(nxt['Close']) - float(nxt['Open'])))
        if avg_body == 0:
            continue
        if direction == 'bullish':
            if (float(c['Close']) < float(c['Open']) and
                    float(nxt['Close']) > float(nxt['Open']) and
                    next_body > 1.5 * avg_body):
                obs.append({'top': float(c['Open']), 'bottom': float(c['Low']), 'index': i, 'type': 'bullish'})
        elif direction == 'bearish':
            if (float(c['Close']) > float(c['Open']) and
                    float(nxt['Close']) < float(nxt['Open']) and
                    next_body > 1.5 * avg_body):
                obs.append({'top': float(c['High']), 'bottom': float(c['Open']), 'index': i, 'type': 'bearish'})
    return obs


def price_near_zone(price, zones, pct=0.005):
    for z in zones:
        if z['bottom'] <= price <= z['top']:
            return True, z
        if (abs(price - z['top']) / price < pct or abs(price - z['bottom']) / price < pct):
            return True, z
    return False, None


# ─── M5 Market Structure ──────────────────────────────────────────────────────

def find_swing_points(df, window=3):
    highs = df['High'].values
    lows = df['Low'].values
    swing_highs = []
    swing_lows = []
    for i in range(window, len(df) - window):
        if all(highs[i] >= highs[i - j] for j in range(1, window + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, window + 1)):
            swing_highs.append({'index': i, 'price': float(highs[i])})
        if all(lows[i] <= lows[i - j] for j in range(1, window + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, window + 1)):
            swing_lows.append({'index': i, 'price': float(lows[i])})
    return swing_highs, swing_lows


def classify_market_structure(swing_highs, swing_lows):
    structure = []
    for i in range(1, len(swing_highs)):
        label = 'HH' if swing_highs[i]['price'] > swing_highs[i - 1]['price'] else 'LH'
        structure.append({'type': label, 'index': swing_highs[i]['index'], 'price': swing_highs[i]['price']})
    for i in range(1, len(swing_lows)):
        label = 'HL' if swing_lows[i]['price'] > swing_lows[i - 1]['price'] else 'LL'
        structure.append({'type': label, 'index': swing_lows[i]['index'], 'price': swing_lows[i]['price']})
    structure.sort(key=lambda x: x['index'])
    return structure


def score_structure(structure, direction):
    recent = structure[-6:] if len(structure) >= 6 else structure
    if direction == 'bullish':
        hh_hl = [s for s in recent if s['type'] in ('HH', 'HL')]
        if len(hh_hl) >= 3:
            return 20, "Strong Bullish Structure (HH+HL)"
        elif len(hh_hl) >= 2:
            return 12, "Bullish Structure (HH+HL)"
        elif len(hh_hl) == 1:
            return 5, "Weak Bullish Structure"
    else:
        lh_ll = [s for s in recent if s['type'] in ('LH', 'LL')]
        if len(lh_ll) >= 3:
            return 20, "Strong Bearish Structure (LH+LL)"
        elif len(lh_ll) >= 2:
            return 12, "Bearish Structure (LH+LL)"
        elif len(lh_ll) == 1:
            return 5, "Weak Bearish Structure"
    return 0, None


# ─── BOS & CHoCH ──────────────────────────────────────────────────────────────

def detect_bos_choch(df, swing_highs, swing_lows, direction):
    bos_list = []
    close = df['Close'].values
    n = len(df)
    if direction == 'bullish' and swing_highs:
        for sh in swing_highs[-4:]:
            for i in range(sh['index'] + 1, n):
                if close[i] > sh['price']:
                    bos_list.append({'type': 'BOS', 'direction': 'bullish', 'index': i, 'level': sh['price']})
                    break
    elif direction == 'bearish' and swing_lows:
        for sl in swing_lows[-4:]:
            for i in range(sl['index'] + 1, n):
                if close[i] < sl['price']:
                    bos_list.append({'type': 'BOS', 'direction': 'bearish', 'index': i, 'level': sl['price']})
                    break
    return bos_list


# ─── Liquidity sweeps ─────────────────────────────────────────────────────────

def detect_liquidity_sweeps(df, swing_highs, swing_lows, direction):
    sweeps = []
    lows = df['Low'].values
    highs = df['High'].values
    close = df['Close'].values
    n = len(df)
    if direction == 'bullish' and swing_lows:
        for sl in swing_lows[-5:]:
            for i in range(sl['index'] + 1, min(sl['index'] + 8, n)):
                if lows[i] < sl['price'] and close[i] > sl['price']:
                    sweeps.append({'type': 'sweep_low', 'index': i, 'level': sl['price']})
                    break
    elif direction == 'bearish' and swing_highs:
        for sh in swing_highs[-5:]:
            for i in range(sh['index'] + 1, min(sh['index'] + 8, n)):
                if highs[i] > sh['price'] and close[i] < sh['price']:
                    sweeps.append({'type': 'sweep_high', 'index': i, 'level': sh['price']})
                    break
    return sweeps


# ─── Candle confirmation ──────────────────────────────────────────────────────

def analyze_confirmation_candle(df, direction):
    if len(df) < 2:
        return 'weak', 0
    last = df.iloc[-1]
    prev = df.iloc[-2]
    o, c, h, l = float(last['Open']), float(last['Close']), float(last['High']), float(last['Low'])
    po, pc, ph, pl = float(prev['Open']), float(prev['Close']), float(prev['High']), float(prev['Low'])
    body = abs(c - o)
    total_range = h - l
    if total_range == 0:
        return 'weak', 0
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    body_ratio = body / total_range
    avg_body = float((df['Close'] - df['Open']).abs().mean())

    if direction == 'bullish':
        if c <= o:
            return 'bearish_candle', 5
        if c > ph and o < pl:
            return 'bullish_engulfing', 100
        if body > 1.5 * avg_body and body_ratio > 0.65:
            return 'displacement', 85
        if lower_wick > 2 * body and c > (l + total_range * 0.6):
            return 'rejection_wick', 75
        if (h - c) < 0.15 * total_range and body_ratio > 0.55:
            return 'strong_close', 65
        if body_ratio > 0.4:
            return 'weak_bullish', 30
        return 'indecision', 5
    else:
        if c >= o:
            return 'bullish_candle', 5
        if c < pl and o > ph:
            return 'bearish_engulfing', 100
        if body > 1.5 * avg_body and body_ratio > 0.65:
            return 'displacement', 85
        if upper_wick > 2 * body and c < (h - total_range * 0.6):
            return 'rejection_wick', 75
        if (c - l) < 0.15 * total_range and body_ratio > 0.55:
            return 'strong_close', 65
        if body_ratio > 0.4:
            return 'weak_bearish', 30
        return 'indecision', 5


# ─── FVG quality ──────────────────────────────────────────────────────────────

def analyze_fvg_quality(fvg, df):
    touched = 0
    for i in range(fvg['index'] + 1, len(df)):
        lo = float(df['Low'].iloc[i])
        hi = float(df['High'].iloc[i])
        if lo <= fvg['top'] and hi >= fvg['bottom']:
            touched += 1
    if touched == 0:
        return 'fresh', 100
    elif touched <= 1:
        return 'light_touch', 60
    return 'mitigated', 20


# ─── OB quality ───────────────────────────────────────────────────────────────

def analyze_ob_quality(ob, df):
    tests = 0
    for i in range(ob['index'] + 2, len(df)):
        lo = float(df['Low'].iloc[i])
        hi = float(df['High'].iloc[i])
        if lo <= ob['top'] and hi >= ob['bottom']:
            tests += 1
    if tests == 0:
        return 'fresh', 100
    elif tests <= 2:
        return 'moderate', 55
    return 'overtested', 15


# ─── Momentum ─────────────────────────────────────────────────────────────────

def calc_momentum(df):
    recent = df.tail(5)
    bull = int((recent['Close'] > recent['Open']).sum())
    bear = int((recent['Close'] < recent['Open']).sum())
    return bull, bear


def momentum_score(direction, bull, bear):
    if direction == 'bullish':
        if bull >= 4:
            return 10, True
        if bull >= 3:
            return 7, True
        if bull >= 2:
            return 4, False
    else:
        if bear >= 4:
            return 10, True
        if bear >= 3:
            return 7, True
        if bear >= 2:
            return 4, False
    return 0, False


# ─── M5 entry score ───────────────────────────────────────────────────────────

def calc_m5_entry_score(direction, structure, bos_list, sweeps,
                        candle_type, candle_raw_score,
                        fvg_quality, ob_quality,
                        momentum_bull, momentum_bear):
    score = 0
    details = []
    struct_pts, struct_label = score_structure(structure, direction)
    score += struct_pts
    if struct_label:
        details.append(f"✅ {struct_label}")
    recent_bos = [b for b in bos_list if b['direction'] == direction]
    if recent_bos:
        score += 20
        details.append("✅ BOS Confirmed")
    else:
        score += 5
    if sweeps:
        score += 15
        sweep_type = "Low Sweep" if sweeps[-1]['type'] == 'sweep_low' else "High Sweep"
        details.append(f"✅ Liquidity {sweep_type}")
    else:
        score += 3
    candle_pts = max(1, int(candle_raw_score * 0.20))
    score += candle_pts
    label_map = {
        'bullish_engulfing': 'Bullish Engulfing',
        'bearish_engulfing': 'Bearish Engulfing',
        'displacement': 'Displacement Candle',
        'rejection_wick': 'Rejection Wick',
        'strong_close': 'Strong Close',
    }
    if candle_type in label_map:
        details.append(f"✅ {label_map[candle_type]}")
    mom_pts, strong_mom = momentum_score(direction, momentum_bull, momentum_bear)
    score += mom_pts
    if strong_mom:
        details.append("✅ Strong Momentum")
    fvg_pts = {'fresh': 10, 'light_touch': 6, 'mitigated': 2}.get(fvg_quality, 0)
    score += fvg_pts
    if fvg_quality == 'fresh':
        details.append("✅ Fresh Unmitigated FVG")
    ob_pts = {'fresh': 5, 'moderate': 3, 'overtested': 0}.get(ob_quality, 0)
    score += ob_pts
    if ob_quality == 'fresh':
        details.append("✅ Fresh Order Block")
    return min(score, 100), details


# ─── H1 probability score ─────────────────────────────────────────────────────

def calc_h1_score(direction, trend, fvgs, obs, atr):
    score = 0
    if trend == direction:
        score += 35
    if len(fvgs) >= 2:
        score += 35
    elif len(fvgs) == 1:
        score += 20
    if len(obs) >= 2:
        score += 20
    elif len(obs) == 1:
        score += 12
    if atr > 3.0:
        score += 10
    elif atr > 1.5:
        score += 5
    return min(score, 100)


# ─── BREAKOUT MODE (neutral H1) ───────────────────────────────────────────────

def detect_ema200_breakout(m5_df):
    """
    Detects a clean EMA200 breakout on M5 during neutral H1.
    Returns: (direction, breakout_info) or (None, None)

    Rules:
    - Price closes decisively above/below EMA200 (body clears it)
    - Breakout candle has strong momentum (body ratio > 0.60)
    - Previous 2 candles were on opposite side of EMA200 (genuine BO, not chop)
    - Checks last 3 candles for a retest setup after initial break
    """
    close = m5_df['Close'].values
    open_ = m5_df['Open'].values
    high = m5_df['High'].values
    low = m5_df['Low'].values
    ema200 = calc_ema(m5_df['Close'], 200).values
    n = len(m5_df)

    if n < 10:
        return None, None

    # Scan last 5 candles for a breakout
    for i in range(n - 5, n):
        e200 = ema200[i]
        c = close[i]
        o = open_[i]
        h = high[i]
        l = low[i]
        body = abs(c - o)
        total_range = h - l
        if total_range == 0:
            continue
        body_ratio = body / total_range

        # Need previous candles to be on opposite side (genuine break, not chop)
        prev_closes = close[max(0, i - 3):i]
        prev_ema = ema200[max(0, i - 3):i]

        # Bullish breakout: candle body closes above EMA200
        if c > e200 and o < e200 or (c > e200 and all(pc < pe for pc, pe in zip(prev_closes, prev_ema))):
            if body_ratio > 0.55 and c > e200:
                # Check if we are in retest zone (current price near EMA200 after break)
                last_close = close[-1]
                last_ema = ema200[-1]
                retest = abs(last_close - last_ema) / last_ema < 0.003
                return 'bullish', {
                    'breakout_index': i,
                    'breakout_price': c,
                    'ema200': round(float(e200), 2),
                    'body_ratio': round(body_ratio, 2),
                    'retest': retest,
                }

        # Bearish breakout: candle body closes below EMA200
        if c < e200 and o > e200 or (c < e200 and all(pc > pe for pc, pe in zip(prev_closes, prev_ema))):
            if body_ratio > 0.55 and c < e200:
                last_close = close[-1]
                last_ema = ema200[-1]
                retest = abs(last_close - last_ema) / last_ema < 0.003
                return 'bearish', {
                    'breakout_index': i,
                    'breakout_price': c,
                    'ema200': round(float(e200), 2),
                    'body_ratio': round(body_ratio, 2),
                    'retest': retest,
                }

    return None, None


def scan_breakout_mode(m5_df, ema21, ema50, ema200_h1):
    """
    Breakout mode scan during neutral H1.
    Returns a signal dict (with mode='breakout') or None with a reason string.
    """
    direction, bo_info = detect_ema200_breakout(m5_df)
    if direction is None:
        return None, "No M5 EMA200 breakout detected — waiting for break and close"

    # Candle confirmation
    candle_type, candle_raw_score = analyze_confirmation_candle(m5_df, direction)
    if candle_type in ('indecision', 'bearish_candle', 'bullish_candle'):
        return None, f"Breakout found but confirmation candle too weak ({candle_type}) — waiting"

    # Momentum check
    bull_mom, bear_mom = calc_momentum(m5_df)
    mom_pts, strong_mom = momentum_score(direction, bull_mom, bear_mom)
    if not strong_mom:
        return None, "Breakout found but momentum too weak — waiting for continuation"

    # M5 structure
    swing_highs, swing_lows = find_swing_points(m5_df, window=3)
    structure = classify_market_structure(swing_highs, swing_lows)
    bos_list = detect_bos_choch(m5_df, swing_highs, swing_lows, direction)
    sweeps = detect_liquidity_sweeps(m5_df, swing_highs, swing_lows, direction)

    fvgs = detect_fvg(m5_df, direction)[-5:]
    obs = detect_order_blocks(m5_df, direction)[-3:]

    fvg_quality = 'fresh'
    ob_quality = 'fresh'
    if fvgs:
        fvg_quality, _ = analyze_fvg_quality(fvgs[-1], m5_df)
    if obs:
        ob_quality, _ = analyze_ob_quality(obs[-1], m5_df)

    # M5 score
    m5_score, m5_details = calc_m5_entry_score(
        direction, structure, bos_list, sweeps,
        candle_type, candle_raw_score,
        fvg_quality, ob_quality,
        bull_mom, bear_mom
    )

    # Retest bonus
    if bo_info['retest']:
        m5_score = min(m5_score + 10, 100)
        m5_details.append("✅ Retest Confirmation")

    # Breakout mode uses M5 score only (no H1 trend score)
    # Require higher M5 threshold to compensate: 80+
    if m5_score < 80:
        return None, f"Breakout detected but M5 score too low ({m5_score}/100, need 80+)"

    atr_series = calc_atr(m5_df)
    atr = float(atr_series.iloc[-1])
    if np.isnan(atr) or atr == 0:
        return None, "ATR invalid"

    current_price = float(m5_df['Close'].iloc[-1])
    entry = current_price
    sl_dist = atr * 1.0
    tp_dist = sl_dist * 3.0

    if direction == 'bullish':
        sl = round(entry - sl_dist, 2)
        tp = round(entry + tp_dist, 2)
    else:
        sl = round(entry + sl_dist, 2)
        tp = round(entry - tp_dist, 2)

    m5_details.insert(0, f"✅ EMA200 Breakout ({'Bullish' if direction == 'bullish' else 'Bearish'})")
    if bo_info['retest']:
        m5_details.insert(1, "✅ Retest of EMA200 Confirmed")

    return {
        'mode': 'breakout',
        'direction': direction,
        'trend': 'neutral',
        'ema21': round(ema21, 2),
        'ema50': round(ema50, 2),
        'ema200': round(ema200_h1, 2),
        'fvgs': fvgs,
        'obs': obs,
        'recent_fvgs': fvgs,
        'recent_obs': obs,
        'entry': round(entry, 2),
        'sl': sl,
        'tp': tp,
        'atr': round(atr, 2),
        'rr': round(tp_dist / sl_dist, 1),
        'score': m5_score,
        'h1_score': 0,
        'm5_score': m5_score,
        'm5_details': m5_details,
        'pips': round(tp_dist / 0.1),
        'candle_type': candle_type,
        'structure': structure,
        'bos_list': bos_list,
        'sweeps': sweeps,
        'swing_highs': swing_highs,
        'swing_lows': swing_lows,
        'fvg_quality': fvg_quality,
        'ob_quality': ob_quality,
        'bo_info': bo_info,
        'm5_df': m5_df,
        'h1_df': None,
    }, None


# ─── Main scan ────────────────────────────────────────────────────────────────

def scan():
    """Returns (signal_or_None, reason_string)."""
    h1_df = get_h1_data(200)
    m5_df = get_m5_data(100)

    if h1_df is None or m5_df is None:
        return None, "Could not fetch market data — check connection"
    if len(h1_df) < 50 or len(m5_df) < 20:
        return None, "Not enough data bars to analyse"

    trend, ema21, ema50, ema200 = analyze_trend(h1_df)

    # ── NEUTRAL: try breakout mode ──
    if trend == 'neutral':
        signal, bo_reason = scan_breakout_mode(m5_df, ema21, ema50, ema200)
        if signal:
            logger.info(f"BREAKOUT MODE signal fired: {signal['direction']} score={signal['score']}")
            return signal, None
        reason = f"H1 trend is NEUTRAL — {bo_reason}"
        logger.info(reason)
        return None, reason

    direction = trend

    # FVG + OB
    fvgs = detect_fvg(m5_df, direction)
    obs = detect_order_blocks(m5_df, direction)
    current_price = float(m5_df['Close'].iloc[-1])
    recent_fvgs = fvgs[-5:] if len(fvgs) > 5 else fvgs
    recent_obs = obs[-3:] if len(obs) > 3 else obs

    near_fvg, _ = price_near_zone(current_price, recent_fvgs)
    near_ob, _ = price_near_zone(current_price, recent_obs)

    if not near_fvg and not near_ob:
        return None, (
            f"H1 trend: {trend.upper()} — no FVG or Order Block near price ({current_price:.2f})\n"
            f"Waiting for retracement into key zone"
        )

    atr_series = calc_atr(m5_df)
    atr = float(atr_series.iloc[-1])
    if np.isnan(atr) or atr == 0:
        return None, "ATR calculation invalid — market may be closed"

    # Confirmation candle
    last = m5_df.iloc[-1]
    if direction == 'bullish' and float(last['Close']) <= float(last['Open']):
        return None, (
            f"H1 trend: BULLISH — price near zone but no bullish confirmation candle yet\n"
            f"Waiting for bullish close"
        )
    if direction == 'bearish' and float(last['Close']) >= float(last['Open']):
        return None, (
            f"H1 trend: BEARISH — price near zone but no bearish confirmation candle yet\n"
            f"Waiting for bearish close"
        )

    # M5 precision
    swing_highs, swing_lows = find_swing_points(m5_df, window=3)
    structure = classify_market_structure(swing_highs, swing_lows)
    bos_list = detect_bos_choch(m5_df, swing_highs, swing_lows, direction)
    sweeps = detect_liquidity_sweeps(m5_df, swing_highs, swing_lows, direction)
    candle_type, candle_raw_score = analyze_confirmation_candle(m5_df, direction)
    momentum_bull, momentum_bear = calc_momentum(m5_df)

    fvg_quality = 'fresh'
    ob_quality = 'fresh'
    if recent_fvgs:
        fvg_quality, _ = analyze_fvg_quality(recent_fvgs[-1], m5_df)
    if recent_obs:
        ob_quality, _ = analyze_ob_quality(recent_obs[-1], m5_df)

    if candle_type in ('indecision', 'bearish_candle', 'bullish_candle'):
        return None, (
            f"H1 trend: {trend.upper()} — price in zone but candle too weak ({candle_type})\n"
            f"Waiting for engulfing / displacement / rejection wick"
        )

    h1_score = calc_h1_score(direction, trend, recent_fvgs, recent_obs, atr)
    m5_score, m5_details = calc_m5_entry_score(
        direction, structure, bos_list, sweeps,
        candle_type, candle_raw_score,
        fvg_quality, ob_quality,
        momentum_bull, momentum_bear
    )
    combined_score = int(h1_score * 0.60 + m5_score * 0.40)
    logger.info(f"H1={h1_score} M5={m5_score} Combined={combined_score} dir={direction}")

    if combined_score < 85:
        return None, (
            f"H1 trend: {trend.upper()} — score too low to fire\n"
            f"H1 score: {h1_score}  M5 score: {m5_score}  Combined: {combined_score}/100 (need 85+)\n"
            f"Missing: {'BOS confirmation' if not bos_list else ''} "
            f"{'strong momentum' if momentum_bull < 3 and momentum_bear < 3 else ''}"
        ).strip()

    entry = current_price
    sl_dist = atr * 1.0
    tp_dist = sl_dist * 3.0

    if direction == 'bullish':
        sl = round(entry - sl_dist, 2)
        tp = round(entry + tp_dist, 2)
    else:
        sl = round(entry + sl_dist, 2)
        tp = round(entry - tp_dist, 2)

    return {
        'mode': 'trend',
        'direction': direction,
        'trend': trend,
        'ema21': round(ema21, 2),
        'ema50': round(ema50, 2),
        'ema200': round(ema200, 2),
        'fvgs': fvgs,
        'obs': obs,
        'recent_fvgs': recent_fvgs,
        'recent_obs': recent_obs,
        'entry': round(entry, 2),
        'sl': sl,
        'tp': tp,
        'atr': round(atr, 2),
        'rr': round(tp_dist / sl_dist, 1),
        'score': combined_score,
        'h1_score': h1_score,
        'm5_score': m5_score,
        'm5_details': m5_details,
        'pips': round(tp_dist / 0.1),
        'candle_type': candle_type,
        'structure': structure,
        'bos_list': bos_list,
        'sweeps': sweeps,
        'swing_highs': swing_highs,
        'swing_lows': swing_lows,
        'fvg_quality': fvg_quality,
        'ob_quality': ob_quality,
        'm5_df': m5_df,
        'h1_df': h1_df,
    }, None
