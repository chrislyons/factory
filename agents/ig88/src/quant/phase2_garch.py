#!/usr/bin/env python3
"""Phase 2: GARCH Modeling and Regime Detection for SOL/USDT Scalping.

Implements:
1. GARCH(1,1) conditional volatility modeling
2. GJR-GARCH asymmetric volatility modeling
3. 4-regime classification (vol x direction)
4. BTC-SOL rolling correlation analysis
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from arch import arch_model
from scipy import stats
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
PLOTS = ROOT / 'docs' / 'ig88' / 'plots'
PLOTS.mkdir(parents=True, exist_ok=True)

def load_data():
    """Load SOL, BTC, ETH parquet files and compute log returns."""
    dfs = {}
    for sym in ['sol', 'btc', 'eth']:
        path = DATA / f'{sym}_usdt_1min.parquet'
        df = pd.read_parquet(path)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').set_index('timestamp')
        df['log_return'] = np.log(df['close'] / df['close'].shift(1))
        df = df.dropna(subset=['log_return'])
        dfs[sym] = df
        print(f'{sym.upper()}: {len(df):,} rows, {df.index.min()} to {df.index.max()}')
    return dfs


def fit_garch(returns, model_type='Garch', title='GARCH(1,1)'):
    """Fit a GARCH or GJR-GARCH model and return results."""
    # Scale returns to percentage for numerical stability
    scaled = returns * 100
    am = arch_model(scaled, vol=model_type, p=1, o=1 if model_type == 'GARCH' else 0, q=1,
                    dist='normal', mean='Constant', rescale=False)
    if model_type == 'GJR-GARCH':
        am = arch_model(scaled, vol='GARCH', p=1, o=1, q=1,
                        dist='normal', mean='Constant', rescale=False)
    else:
        am = arch_model(scaled, vol='GARCH', p=1, o=0, q=1,
                        dist='normal', mean='Constant', rescale=False)
    
    res = am.fit(disp='off', show_warning=False)
    return res, scaled


def section_garch(dfs):
    """GARCH(1,1) analysis on SOL returns."""
    print('\n' + '='*80)
    print('SECTION 1: GARCH(1,1) MODEL — SOL/USDT')
    print('='*80)
    
    sol_ret = dfs['sol']['log_return']
    
    # Fit GARCH(1,1)
    res, scaled = fit_garch(sol_ret, model_type='Garch')
    print(f'\nModel: GARCH(1,1)')
    print(res.summary().tables[0])
    print(res.summary().tables[1])
    
    # Extract parameters
    params = res.params
    print(f'\nParameters:')
    print(f'  omega (constant):  {params["omega"]:.6f}')
    print(f'  alpha[1] (ARCH):   {params["alpha[1]"]:.6f}')
    print(f'  beta[1] (GARCH):   {params["beta[1]"]:.6f}')
    print(f'  Persistence (a+b): {params["alpha[1]"] + params["beta[1]"]:.6f}')
    
    # Model fit stats
    print(f'\nFit Statistics:')
    print(f'  Log-Likelihood: {res.loglikelihood:.2f}')
    print(f'  AIC: {res.aic:.2f}')
    print(f'  BIC: {res.bic:.2f}')
    
    # Conditional volatility
    cond_vol = res.conditional_volatility / 100  # back to decimal
    
    # Forecast evaluation: compare conditional variance to realized variance
    # Use 60-min rolling realized variance as proxy
    realized_var = sol_ret.rolling(60).var()
    cond_var = (cond_vol ** 2)
    
    # Align
    common_idx = realized_var.dropna().index.intersection(cond_var.index)
    rv = realized_var.loc[common_idx]
    cv = cond_var.loc[common_idx]
    
    mse = ((rv - cv) ** 2).mean()
    mae = (rv - cv).abs().mean()
    print(f'\nVariance Forecast Accuracy (vs 60-min realized):')
    print(f'  MSE: {mse:.2e}')
    print(f'  MAE: {mae:.2e}')
    print(f'  Correlation(cond_var, realized_var): {rv.corr(cv):.4f}')
    
    # 1-step ahead forecast
    fcast = res.forecast(horizon=5)
    print(f'\n1-Step Ahead Volatility Forecast: {np.sqrt(fcast.variance.iloc[-1, 0]) / 100:.6f}')
    print(f'5-Step Ahead Volatility Forecast: {np.sqrt(fcast.variance.iloc[-1, 4]) / 100:.6f}')
    
    # Plot conditional volatility
    fig, axes = plt.subplots(2, 1, figsize=(14, 8))
    axes[0].plot(cond_vol.index[-5000:], cond_vol.iloc[-5000:], linewidth=0.5, color='steelblue')
    axes[0].set_title('GARCH(1,1) Conditional Volatility — SOL/USDT (last 5000 candles)')
    axes[0].set_ylabel('Volatility (σ)')
    
    axes[1].plot(realized_var.index[-5000:], realized_var.iloc[-5000:], linewidth=0.5, color='coral', label='Realized Var')
    axes[1].plot(cond_var.index[-5000:], cond_var.iloc[-5000:], linewidth=0.5, color='steelblue', label='Conditional Var')
    axes[1].set_title('Conditional vs Realized Variance')
    axes[1].set_ylabel('Variance')
    axes[1].legend()
    plt.tight_layout()
    plt.savefig(PLOTS / 'garch11_volatility.png', dpi=150)
    plt.close()
    print(f'\nPlot saved: docs/ig88/plots/garch11_volatility.png')
    
    return res, cond_vol


def section_gjr_garch(dfs):
    """GJR-GARCH asymmetric model."""
    print('\n' + '='*80)
    print('SECTION 2: GJR-GARCH (ASYMMETRIC) MODEL — SOL/USDT')
    print('='*80)
    
    sol_ret = dfs['sol']['log_return']
    scaled = sol_ret * 100
    
    # Fit GJR-GARCH (o=1 adds asymmetry term)
    am_gjr = arch_model(scaled, vol='GARCH', p=1, o=1, q=1,
                        dist='normal', mean='Constant', rescale=False)
    res_gjr = am_gjr.fit(disp='off', show_warning=False)
    
    # Also fit standard GARCH for comparison
    am_std = arch_model(scaled, vol='GARCH', p=1, o=0, q=1,
                        dist='normal', mean='Constant', rescale=False)
    res_std = am_std.fit(disp='off', show_warning=False)
    
    print(f'\nGJR-GARCH Parameters:')
    print(res_gjr.summary().tables[1])
    
    params = res_gjr.params
    print(f'\nKey Parameters:')
    print(f'  omega:     {params["omega"]:.6f}')
    print(f'  alpha[1]:  {params["alpha[1]"]:.6f}')
    print(f'  gamma[1]:  {params["gamma[1]"]:.6f}  (asymmetry/leverage)')
    print(f'  beta[1]:   {params["beta[1]"]:.6f}')
    
    # Test gamma significance
    tstat = res_gjr.tvalues['gamma[1]']
    pval = res_gjr.pvalues['gamma[1]']
    print(f'\nAsymmetry Test (gamma):')
    print(f'  t-statistic: {tstat:.4f}')
    print(f'  p-value:     {pval:.6f}')
    print(f'  Significant at 5%: {"YES" if pval < 0.05 else "NO"}')
    if params['gamma[1]'] > 0:
        print(f'  Interpretation: Negative shocks increase volatility MORE than positive shocks')
    else:
        print(f'  Interpretation: Positive shocks increase volatility MORE (inverse leverage)')
    
    # Model comparison
    print(f'\nModel Comparison:')
    print(f'{"Metric":<20} {"GARCH(1,1)":>15} {"GJR-GARCH":>15}')
    print(f'{"":-<50}')
    print(f'{"Log-Likelihood":<20} {res_std.loglikelihood:>15.2f} {res_gjr.loglikelihood:>15.2f}')
    print(f'{"AIC":<20} {res_std.aic:>15.2f} {res_gjr.aic:>15.2f}')
    print(f'{"BIC":<20} {res_std.bic:>15.2f} {res_gjr.bic:>15.2f}')
    print(f'{"Num Params":<20} {res_std.num_params:>15d} {res_gjr.num_params:>15d}')
    
    preferred = 'GJR-GARCH' if res_gjr.aic < res_std.aic else 'GARCH(1,1)'
    print(f'\nPreferred model (AIC): {preferred}')
    
    return res_gjr, res_std


def section_regime_classification(dfs):
    """4-regime classification based on volatility and direction."""
    print('\n' + '='*80)
    print('SECTION 3: 4-REGIME CLASSIFICATION — SOL/USDT')
    print('='*80)
    
    sol = dfs['sol'].copy()
    
    # Rolling realized volatility (60-min window)
    sol['realized_vol'] = sol['log_return'].rolling(60).std()
    
    # Rolling returns (15-min window) for direction
    sol['rolling_ret'] = sol['log_return'].rolling(15).sum()
    
    # Median volatility as threshold
    vol_median = sol['realized_vol'].median()
    print(f'\nVolatility Threshold (median): {vol_median:.6f}')
    
    # Classify regimes
    sol['vol_regime'] = np.where(sol['realized_vol'] > vol_median, 'high_vol', 'low_vol')
    sol['dir_regime'] = np.where(sol['rolling_ret'] >= 0, 'up', 'down')
    sol['regime'] = sol['vol_regime'] + '_' + sol['dir_regime']
    
    sol_clean = sol.dropna(subset=['regime'])
    
    # Regime statistics
    print(f'\nRegime Distribution:')
    regime_counts = sol_clean['regime'].value_counts()
    regime_pcts = sol_clean['regime'].value_counts(normalize=True) * 100
    for regime in ['low_vol_up', 'low_vol_down', 'high_vol_up', 'high_vol_down']:
        count = regime_counts.get(regime, 0)
        pct = regime_pcts.get(regime, 0)
        avg_ret = sol_clean[sol_clean['regime'] == regime]['log_return'].mean() * 100
        vol = sol_clean[sol_clean['regime'] == regime]['log_return'].std() * 100
        sharpe_1min = avg_ret / vol if vol > 0 else 0
        # Annualize: 525,600 minutes/year
        sharpe_ann = sharpe_1min * np.sqrt(525600)
        print(f'  {regime:<16} {count:>8,} candles ({pct:5.1f}%)  '
              f'avg_ret={avg_ret:+.4f}%  vol={vol:.4f}%  Sharpe(ann)={sharpe_ann:+.2f}')
    
    # Regime persistence (average run length)
    print(f'\nRegime Persistence (average consecutive candles):')
    regime_series = sol_clean['regime']
    regime_changes = regime_series != regime_series.shift(1)
    regime_runs = regime_changes.cumsum()
    for regime in ['low_vol_up', 'low_vol_down', 'high_vol_up', 'high_vol_down']:
        mask = regime_series == regime
        if mask.sum() > 0:
            runs = regime_runs[mask]
            run_lengths = runs.groupby(runs).count()
            avg_run = run_lengths.mean()
            max_run = run_lengths.max()
            print(f'  {regime:<16} avg={avg_run:.1f} candles, max={max_run} candles')
    
    # Transition matrix
    print(f'\nRegime Transition Matrix (row=from, col=to):')
    regimes = ['low_vol_up', 'low_vol_down', 'high_vol_up', 'high_vol_down']
    current = regime_series.iloc[:-1].values
    next_regime = regime_series.iloc[1:].values
    
    trans_matrix = pd.DataFrame(0.0, index=regimes, columns=regimes)
    for i in range(len(current)):
        if current[i] in regimes and next_regime[i] in regimes:
            trans_matrix.loc[current[i], next_regime[i]] += 1
    
    # Normalize rows
    trans_pct = trans_matrix.div(trans_matrix.sum(axis=1), axis=0) * 100
    print(trans_pct.round(2).to_string())
    
    # Regime detection lag analysis
    # Measure how many candles after a "true" regime change the classifier detects it
    # True regime change = when underlying vol or direction actually shifts
    # We use a shorter lookback (5-min) as ground truth vs our 60/15-min classifier
    sol['fast_vol'] = sol['log_return'].rolling(5).std()
    sol['fast_ret'] = sol['log_return'].rolling(5).sum()
    fast_vol_median = sol['fast_vol'].median()
    sol['fast_regime'] = (np.where(sol['fast_vol'] > fast_vol_median, 'high_vol', 'low_vol') + '_' +
                          np.where(sol['fast_ret'] >= 0, 'up', 'down'))
    
    # Compare: when fast_regime changes, how many candles until regime changes?
    sol_lag = sol.dropna()
    fast_changes = sol_lag['fast_regime'] != sol_lag['fast_regime'].shift(1)
    slow_changes = sol_lag['regime'] != sol_lag['regime'].shift(1)
    
    # For each fast change, find next slow change
    fast_change_idx = np.where(fast_changes)[0]
    slow_change_idx = np.where(slow_changes)[0]
    
    lags = []
    for fi in fast_change_idx[:10000]:  # sample for speed
        later = slow_change_idx[slow_change_idx > fi]
        if len(later) > 0:
            lag = later[0] - fi
            if lag <= 30:  # cap at 30 candles
                lags.append(lag)
    
    if lags:
        lags = np.array(lags)
        print(f'\nRegime Detection Lag (vs 5-min ground truth):')
        print(f'  Mean lag:   {lags.mean():.1f} candles')
        print(f'  Median lag: {np.median(lags):.1f} candles')
        print(f'  P90 lag:    {np.percentile(lags, 90):.0f} candles')
        print(f'  % detected within 3 candles: {(lags <= 3).mean()*100:.1f}%')
    
    # Save regime stats CSV
    regime_stats = []
    for regime in regimes:
        mask = sol_clean['regime'] == regime
        rets = sol_clean.loc[mask, 'log_return']
        regime_stats.append({
            'regime': regime,
            'count': mask.sum(),
            'pct': mask.mean() * 100,
            'mean_return': rets.mean(),
            'std_return': rets.std(),
            'sharpe_ann': (rets.mean() / rets.std() * np.sqrt(525600)) if rets.std() > 0 else 0,
            'skewness': rets.skew(),
            'kurtosis': rets.kurtosis()
        })
    stats_df = pd.DataFrame(regime_stats)
    stats_df.to_csv(DATA / 'regime_statistics.csv', index=False)
    print(f'\nRegime statistics saved: data/regime_statistics.csv')
    
    # Plot regime distribution over time
    fig, ax = plt.subplots(figsize=(14, 4))
    regime_map = {'low_vol_up': 0, 'low_vol_down': 1, 'high_vol_up': 2, 'high_vol_down': 3}
    colors = {'low_vol_up': '#2ecc71', 'low_vol_down': '#f39c12', 'high_vol_up': '#3498db', 'high_vol_down': '#e74c3c'}
    regime_numeric = sol_clean['regime'].map(regime_map)
    scatter_sample = regime_numeric.iloc[-10000:]  # last 10k for visibility
    for regime, color in colors.items():
        mask = sol_clean['regime'].iloc[-10000:] == regime
        ax.scatter(sol_clean.index[-10000:][mask], regime_numeric.iloc[-10000:][mask],
                   c=color, s=1, alpha=0.5, label=regime)
    ax.set_yticks([0, 1, 2, 3])
    ax.set_yticklabels(['low_vol_up', 'low_vol_down', 'high_vol_up', 'high_vol_down'])
    ax.set_title('Regime Classification Over Time (last 10k candles)')
    ax.legend(markerscale=10)
    plt.tight_layout()
    plt.savefig(PLOTS / 'regime_classification.png', dpi=150)
    plt.close()
    print(f'Plot saved: docs/ig88/plots/regime_classification.png')
    
    # Transition matrix heatmap
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(trans_pct, annot=True, fmt='.1f', cmap='YlOrRd', ax=ax)
    ax.set_title('Regime Transition Probabilities (%)')
    ax.set_xlabel('To Regime')
    ax.set_ylabel('From Regime')
    plt.tight_layout()
    plt.savefig(PLOTS / 'transition_matrix.png', dpi=150)
    plt.close()
    print(f'Plot saved: docs/ig88/plots/transition_matrix.png')
    
    return sol_clean, trans_pct, stats_df


def section_correlation(dfs):
    """BTC-SOL rolling correlation analysis."""
    print('\n' + '='*80)
    print('SECTION 4: BTC-SOL ROLLING CORRELATION')
    print('='*80)
    
    # Align timestamps
    sol_ret = dfs['sol']['log_return']
    btc_ret = dfs['btc']['log_return']
    
    common_idx = sol_ret.index.intersection(btc_ret.index)
    sol_r = sol_ret.loc[common_idx]
    btc_r = btc_ret.loc[common_idx]
    print(f'\nCommon timestamps: {len(common_idx):,}')
    
    windows = {'60min': 60, '240min': 240, '1440min': 1440}
    
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    
    for i, (label, window) in enumerate(windows.items()):
        rolling_corr = sol_r.rolling(window).corr(btc_r)
        rolling_corr = rolling_corr.dropna()
        
        mean_corr = rolling_corr.mean()
        std_corr = rolling_corr.std()
        min_corr = rolling_corr.min()
        max_corr = rolling_corr.max()
        
        # Decorrelation periods (corr < 0.3)
        decorr_mask = rolling_corr < 0.3
        decorr_pct = decorr_mask.mean() * 100
        
        # Count decorrelation episodes and their duration
        decorr_changes = decorr_mask != decorr_mask.shift(1)
        decorr_runs = decorr_changes.cumsum()
        decorr_episodes = decorr_runs[decorr_mask]
        if len(decorr_episodes) > 0:
            episode_lengths = decorr_episodes.groupby(decorr_episodes).count()
            n_episodes = len(episode_lengths)
            avg_duration = episode_lengths.mean()
            max_duration = episode_lengths.max()
        else:
            n_episodes = avg_duration = max_duration = 0
        
        # Negative correlation periods
        neg_corr_pct = (rolling_corr < 0).mean() * 100
        
        print(f'\n{label} Rolling Correlation (BTC-SOL):')
        print(f'  Mean: {mean_corr:.4f}')
        print(f'  Std:  {std_corr:.4f}')
        print(f'  Min:  {min_corr:.4f}')
        print(f'  Max:  {max_corr:.4f}')
        print(f'  Decorrelation (< 0.3): {decorr_pct:.1f}% of time')
        print(f'  Negative correlation:  {neg_corr_pct:.1f}% of time')
        print(f'  Decorrelation episodes: {n_episodes}')
        print(f'  Avg episode duration: {avg_duration:.0f} candles')
        print(f'  Max episode duration: {max_duration:.0f} candles')
        
        # Plot
        axes[i].plot(rolling_corr.index[-20000:], rolling_corr.iloc[-20000:],
                     linewidth=0.5, color='steelblue')
        axes[i].axhline(y=0.3, color='red', linestyle='--', alpha=0.7, label='Decorrelation threshold')
        axes[i].axhline(y=0, color='gray', linestyle='-', alpha=0.3)
        axes[i].set_ylabel(f'{label} Corr')
        axes[i].set_title(f'{label} Rolling Correlation: BTC-SOL')
        axes[i].legend()
        axes[i].set_ylim(-0.5, 1.0)
    
    plt.tight_layout()
    plt.savefig(PLOTS / 'btc_sol_correlation.png', dpi=150)
    plt.close()
    print(f'\nPlot saved: docs/ig88/plots/btc_sol_correlation.png')
    
    # ETH-SOL correlation for reference
    eth_ret = dfs['eth']['log_return']
    common_eth = sol_ret.index.intersection(eth_ret.index)
    eth_corr_60 = sol_ret.loc[common_eth].rolling(60).corr(eth_ret.loc[common_eth]).dropna()
    print(f'\nETH-SOL 60min Correlation: mean={eth_corr_60.mean():.4f}, std={eth_corr_60.std():.4f}')


def main():
    print('='*80)
    print('IG-88 PHASE 2: GARCH MODELING & REGIME DETECTION')
    print('='*80)
    
    dfs = load_data()
    
    garch_res, cond_vol = section_garch(dfs)
    gjr_res, std_res = section_gjr_garch(dfs)
    sol_regimes, trans_pct, stats_df = section_regime_classification(dfs)
    section_correlation(dfs)
    
    print('\n' + '='*80)
    print('PHASE 2 ANALYSIS COMPLETE')
    print('='*80)
    print(f'\nOutputs:')
    print(f'  - data/regime_statistics.csv')
    print(f'  - docs/ig88/plots/garch11_volatility.png')
    print(f'  - docs/ig88/plots/regime_classification.png')
    print(f'  - docs/ig88/plots/transition_matrix.png')
    print(f'  - docs/ig88/plots/btc_sol_correlation.png')


if __name__ == '__main__':
    main()
