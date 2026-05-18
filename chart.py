import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import mplfinance as mpf
import io
import logging

logger = logging.getLogger(__name__)

DARK_BG = '#131722'
GRID_COLOR = '#2a2e39'
TEXT_COLOR = '#d1d4dc'


def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def _build_style():
    mc = mpf.make_marketcolors(
        up='#26a69a', down='#ef5350',
        edge='inherit',
        wick={'up': '#26a69a', 'down': '#ef5350'},
        volume='in'
    )
    return mpf.make_mpf_style(
        marketcolors=mc,
        facecolor=DARK_BG,
        edgecolor=GRID_COLOR,
        gridcolor=GRID_COLOR,
        gridstyle='--',
        rc={
            'axes.labelcolor': TEXT_COLOR,
            'xtick.color': TEXT_COLOR,
            'ytick.color': TEXT_COLOR,
            'figure.facecolor': DARK_BG,
            'axes.titlecolor': TEXT_COLOR,
        }
    )


def _draw_fvg_ob_zones(ax, fvgs, obs, direction):
    fvg_color = '#00bfff' if direction == 'bullish' else '#ff6b6b'
    ob_color = '#26a69a' if direction == 'bullish' else '#ef5350'
    for fvg in fvgs:
        ax.axhspan(fvg['bottom'], fvg['top'], alpha=0.12, color=fvg_color)
        ax.axhline(fvg['top'], color=fvg_color, alpha=0.3, linestyle=':', linewidth=0.8)
        ax.axhline(fvg['bottom'], color=fvg_color, alpha=0.3, linestyle=':', linewidth=0.8)
    for ob in obs:
        ax.axhspan(ob['bottom'], ob['top'], alpha=0.18, color=ob_color)


def _draw_structure_labels(ax, structure, chart_start_idx, n_chart):
    """Draw HH/HL/LH/LL labels on swing points within chart window."""
    color_map = {
        'HH': '#00ff88', 'HL': '#26a69a',
        'LH': '#ff4444', 'LL': '#ff6b6b'
    }
    va_map = {'HH': 'bottom', 'LH': 'bottom', 'HL': 'top', 'LL': 'top'}
    for s in structure:
        rel_idx = s['index'] - chart_start_idx
        if 0 <= rel_idx < n_chart:
            color = color_map.get(s['type'], '#ffffff')
            va = va_map.get(s['type'], 'center')
            ax.annotate(
                s['type'],
                xy=(rel_idx, s['price']),
                fontsize=7,
                color=color,
                fontweight='bold',
                va=va,
                ha='center',
            )


def _draw_bos_markers(ax, bos_list, chart_start_idx, n_chart):
    """Draw vertical BOS lines."""
    for bos in bos_list[-3:]:
        rel_idx = bos['index'] - chart_start_idx
        if 0 <= rel_idx < n_chart:
            ax.axvline(rel_idx, color='#ffe066', linewidth=1.0, linestyle='--', alpha=0.6)
            ax.text(rel_idx + 0.2, ax.get_ylim()[1] * 0.995, 'BOS',
                    color='#ffe066', fontsize=7, fontweight='bold', va='top')


def _draw_sweep_zones(ax, sweeps, df_chart, chart_start_idx, n_chart):
    """Highlight liquidity sweep candles."""
    for sw in sweeps[-3:]:
        rel_idx = sw['index'] - chart_start_idx
        if 0 <= rel_idx < n_chart:
            label = 'SWEEP' if sw['type'] == 'sweep_low' else 'SWEEP'
            color = '#00bfff' if sw['type'] == 'sweep_low' else '#ff6b6b'
            ax.axvspan(rel_idx - 0.4, rel_idx + 0.4, alpha=0.15, color=color)
            ax.text(rel_idx, ax.get_ylim()[0], label,
                    color=color, fontsize=6, va='bottom', ha='center', fontweight='bold')


def _draw_legend(ax, fvgs, obs, direction):
    fvg_color = '#00bfff' if direction == 'bullish' else '#ff6b6b'
    ob_color = '#26a69a' if direction == 'bullish' else '#ef5350'
    elements = [
        mpatches.Patch(facecolor=fvg_color, alpha=0.4, label='FVG Zone'),
        mpatches.Patch(facecolor=ob_color, alpha=0.5, label='Order Block'),
        plt.Line2D([0], [0], color='#00bfff', linewidth=1.5, label='EMA 21'),
        plt.Line2D([0], [0], color='#ffa500', linewidth=1.5, label='EMA 50'),
        plt.Line2D([0], [0], color='#ff4444', linewidth=1.5, label='EMA 200'),
    ]
    ax.legend(handles=elements, loc='upper left',
              framealpha=0.25, fontsize=7.5, labelcolor='white', facecolor=DARK_BG)


def generate_chart(signal):
    """Signal chart — includes entry, SL, TP + M5 analysis overlays."""
    try:
        full_df = signal['m5_df']
        chart_start = max(0, len(full_df) - 60)
        m5_df = full_df.iloc[chart_start:].copy()
        n = len(m5_df)

        direction = signal['direction']
        recent_fvgs = signal.get('recent_fvgs', [])
        recent_obs = signal.get('recent_obs', [])
        structure = signal.get('structure', [])
        bos_list = signal.get('bos_list', [])
        sweeps = signal.get('sweeps', [])
        entry, sl, tp = signal['entry'], signal['sl'], signal['tp']
        h1_score = signal.get('h1_score', 0)
        m5_score = signal.get('m5_score', 0)
        combined = signal.get('score', 0)
        candle_type = signal.get('candle_type', '')

        close = m5_df['Close']
        ema21 = calc_ema(close, 21)
        ema50 = calc_ema(close, 50)
        ema200 = calc_ema(close, 200)

        add_plots = [
            mpf.make_addplot(ema21, color='#00bfff', width=1.2),
            mpf.make_addplot(ema50, color='#ffa500', width=1.2),
            mpf.make_addplot(ema200, color='#ff4444', width=1.5),
        ]

        dir_label = 'BUY' if direction == 'bullish' else 'SELL'
        fig, axes = mpf.plot(
            m5_df, type='candle', style=_build_style(),
            addplot=add_plots, returnfig=True, figsize=(15, 9),
            title=f'\n  XAUUSD M5  —  {dir_label} SIGNAL  |  H1: {h1_score}  M5: {m5_score}  Score: {combined}/100',
            ylabel='Price (USD)', tight_layout=True,
        )
        ax = axes[0]

        _draw_fvg_ob_zones(ax, recent_fvgs, recent_obs, direction)
        _draw_structure_labels(ax, structure, chart_start, n)
        _draw_bos_markers(ax, bos_list, chart_start, n)
        _draw_sweep_zones(ax, sweeps, m5_df, chart_start, n)

        # Entry / SL / TP lines
        ax.axhline(entry, color='#ffffff', linewidth=1.8, linestyle='-', zorder=5)
        ax.axhline(sl, color='#ff4444', linewidth=1.8, linestyle='--', zorder=5)
        ax.axhline(tp, color='#00ff88', linewidth=1.8, linestyle='--', zorder=5)
        ax.text(n - 1, entry, f'  ENTRY {entry:.2f}', color='white', fontsize=9, va='center', fontweight='bold')
        ax.text(n - 1, sl, f'  SL {sl:.2f}', color='#ff4444', fontsize=9, va='center', fontweight='bold')
        ax.text(n - 1, tp, f'  TP {tp:.2f}', color='#00ff88', fontsize=9, va='center', fontweight='bold')

        # Highlight last (entry) candle
        ax.axvspan(n - 1.4, n - 0.6, alpha=0.25, color='#ffffff', zorder=4)

        # Candle type label
        if candle_type:
            ax.text(n - 1, ax.get_ylim()[0], f'  {candle_type.replace("_", " ").upper()}',
                    color='#ffe066', fontsize=7, va='bottom', ha='left')

        # Score box
        score_text = f'H1 Score: {h1_score}\nM5 Score: {m5_score}\nCombined: {combined}/100'
        ax.text(0.01, 0.02, score_text, transform=ax.transAxes,
                fontsize=8, color='white', va='bottom', ha='left',
                bbox=dict(facecolor=DARK_BG, edgecolor='#444', alpha=0.8, boxstyle='round,pad=0.4'))

        _draw_legend(ax, recent_fvgs, recent_obs, direction)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=DARK_BG)
        buf.seek(0)
        plt.close(fig)
        return buf

    except Exception as e:
        logger.error(f"Chart generation failed: {e}", exc_info=True)
        plt.close('all')
        return None


def generate_live_chart(m5_df, h1_df, trend):
    """Live market overview chart — EMAs, FVG/OB zones, structure labels."""
    try:
        from scanner import detect_fvg, detect_order_blocks, find_swing_points, classify_market_structure

        chart_start = max(0, len(m5_df) - 60)
        df = m5_df.iloc[chart_start:].copy()
        n = len(df)

        close = df['Close']
        ema21 = calc_ema(close, 21)
        ema50 = calc_ema(close, 50)
        ema200 = calc_ema(close, 200)

        add_plots = [
            mpf.make_addplot(ema21, color='#00bfff', width=1.2),
            mpf.make_addplot(ema50, color='#ffa500', width=1.2),
            mpf.make_addplot(ema200, color='#ff4444', width=1.5),
        ]

        direction = trend if trend != 'neutral' else 'bullish'
        fvgs = detect_fvg(m5_df, direction)[-5:]
        obs = detect_order_blocks(m5_df, direction)[-3:]

        swing_highs, swing_lows = find_swing_points(m5_df, window=3)
        structure = classify_market_structure(swing_highs, swing_lows)

        trend_label = trend.upper()
        fig, axes = mpf.plot(
            df, type='candle', style=_build_style(),
            addplot=add_plots, returnfig=True, figsize=(15, 9),
            title=f'\n  XAUUSD M5  —  Live Chart  |  H1 Trend: {trend_label}',
            ylabel='Price (USD)', tight_layout=True,
        )
        ax = axes[0]

        _draw_fvg_ob_zones(ax, fvgs, obs, direction)
        _draw_structure_labels(ax, structure, chart_start, n)
        _draw_legend(ax, fvgs, obs, direction)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=DARK_BG)
        buf.seek(0)
        plt.close(fig)
        return buf

    except Exception as e:
        logger.error(f"Live chart generation failed: {e}", exc_info=True)
        plt.close('all')
        return None
