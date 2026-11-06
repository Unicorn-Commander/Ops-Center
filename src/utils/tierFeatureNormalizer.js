/**
 * Normalize tier feature responses from either supported API shape.
 *
 * @param {unknown} data - A list of tier records or a tier-code keyed object.
 * @returns {Array<{tier_code: string, features: unknown[]}>}
 */
export const normalizeTierFeatures = (data) => {
  if (Array.isArray(data)) {
    return data;
  }

  if (data && typeof data === 'object') {
    return Object.entries(data).map(([tier_code, features]) => ({
      tier_code,
      features
    }));
  }

  return [];
};

export default normalizeTierFeatures;
