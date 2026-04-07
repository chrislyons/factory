// IG-88 Configuration Module
// Centralizes all runtime configuration

import { existsSync, readFileSync } from 'fs';
import { KILL_ZONE_LADDER, type KillZonePhase } from './types.js';

export interface Config {
  // Capital management
  capital: number;
  phase: KillZonePhase;
  maxRiskPercent: number;

  // Matrix alerting
  matrixEnabled: boolean;
  matrixHomeserver: string;
  matrixRoomId: string;
  matrixTokenFile: string;

  // Price feeds
  priceSourcePriority: string[];
  priceVarianceThreshold: number; // max acceptable variance between sources

  // Scheduling
  cycleTimesUtc: string[]; // HH:MM format

  // Safety
  wrShutdown: number;
  wrAlert: number;
  maxDailyLoss: number; // percentage
  maxConsecutiveLosses: number;

  // Paths
  logDir: string;
  validationDir: string;
}

// Determine Kill Zone phase from capital
export function getPhaseFromCapital(capital: number): KillZonePhase {
  for (const phase of [5, 4, 3, 2, 1, 0] as KillZonePhase[]) {
    const config = KILL_ZONE_LADDER[phase];
    if (capital >= config.capitalRange[0]) {
      return phase;
    }
  }
  return 0;
}

// Load environment variable with default
function env(key: string, defaultValue: string): string {
  return process.env[key] || defaultValue;
}

function envNum(key: string, defaultValue: number): number {
  const val = process.env[key];
  return val ? parseFloat(val) : defaultValue;
}

function envBool(key: string, defaultValue: boolean): boolean {
  const val = process.env[key];
  if (!val) return defaultValue;
  return val.toLowerCase() === 'true' || val === '1';
}

// Load .env file if exists
export function loadEnvFile(path?: string): void {
  const envPath = path || `${process.env.HOME}/.config/ig88/.env`;
  if (existsSync(envPath)) {
    const content = readFileSync(envPath, 'utf-8');
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (trimmed && !trimmed.startsWith('#')) {
        const [key, ...valueParts] = trimmed.split('=');
        const value = valueParts.join('=').trim();
        if (key && value && !process.env[key]) {
          process.env[key] = value;
        }
      }
    }
  }
}

// Build configuration
export function loadConfig(): Config {
  loadEnvFile();

  const capital = envNum('TRADING_CAPITAL', 1000);
  const phase = getPhaseFromCapital(capital);
  const phaseConfig = KILL_ZONE_LADDER[phase];

  return {
    // Capital management
    capital,
    phase,
    maxRiskPercent: envNum('MAX_RISK_PERCENT', phaseConfig.riskPercent),

    // Matrix alerting
    matrixEnabled: envBool('MATRIX_ENABLED', true),
    matrixHomeserver: env('MATRIX_HOMESERVER', 'https://matrix.org'),
    matrixRoomId: env('MATRIX_ROOM_ID', ''),
    matrixTokenFile: env('MATRIX_TOKEN_FILE', `${process.env.HOME}/.config/ig88/matrix_token`),

    // Price feeds (RP5112 priority order)
    priceSourcePriority: env('PRICE_SOURCES', 'kucoin,coingecko,jupiter,coinpaprika').split(','),
    priceVarianceThreshold: envNum('PRICE_VARIANCE_THRESHOLD', 0.05), // 5%

    // Scheduling
    cycleTimesUtc: env('CYCLE_TIMES_UTC', '13:00,01:00').split(','),

    // Safety (RP5099)
    wrShutdown: envNum('WR_SHUTDOWN', 0.45),
    wrAlert: envNum('WR_ALERT', 0.48),
    maxDailyLoss: envNum('MAX_DAILY_LOSS', 25), // 25%
    maxConsecutiveLosses: envNum('MAX_CONSECUTIVE_LOSSES', 3),

    // Paths
    logDir: env('LOG_DIR', `${process.env.HOME}/projects/ig88/logs`),
    validationDir: env('VALIDATION_DIR', `${process.env.HOME}/projects/ig88/.claude/validation`),
  };
}

// Validate configuration
export function validateConfig(config: Config): string[] {
  const errors: string[] = [];

  if (config.capital < 200) {
    errors.push('Capital must be at least $200 (Kill Zone minimum)');
  }

  if (config.matrixEnabled && !config.matrixRoomId) {
    errors.push('MATRIX_ROOM_ID required when Matrix is enabled');
  }

  if (config.matrixEnabled && !existsSync(config.matrixTokenFile)) {
    errors.push(`Matrix token file not found: ${config.matrixTokenFile}`);
  }

  if (config.maxRiskPercent > 20) {
    errors.push('Max risk percent cannot exceed 20% (safety limit)');
  }

  return errors;
}

// Export default config for CLI usage
export const config = loadConfig();
