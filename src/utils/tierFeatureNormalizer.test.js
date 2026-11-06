import { describe, expect, test } from 'vitest';
import { normalizeTierFeatures } from './tierFeatureNormalizer';

describe('normalizeTierFeatures', () => {
  const fictionalFeatures = [
    { feature_name: 'Lantern analytics', category: 'insights' }
  ];

  test('keeps list-shaped tier features unchanged', () => {
    const response = [
      { tier_code: 'cobalt', features: fictionalFeatures }
    ];

    expect(normalizeTierFeatures(response)).toEqual(response);
  });

  test('converts tier-code keyed features to tier records', () => {
    const response = {
      cobalt: fictionalFeatures,
      juniper: [{ feature_name: 'Juniper exports', category: 'reports' }]
    };

    expect(normalizeTierFeatures(response)).toEqual([
      { tier_code: 'cobalt', features: fictionalFeatures },
      { tier_code: 'juniper', features: response.juniper }
    ]);
  });

  test('returns an empty list for unsupported responses', () => {
    expect(normalizeTierFeatures(null)).toEqual([]);
    expect(normalizeTierFeatures('not tier data')).toEqual([]);
  });
});
