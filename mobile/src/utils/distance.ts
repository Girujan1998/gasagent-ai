const EARTH_RADIUS_MILES = 3958.8;
const MILES_TO_KM = 1.60934;

function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

export function milesToKm(miles: number): number {
  return miles * MILES_TO_KM;
}

export function haversineMiles(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const dLat = toRadians(lat2 - lat1);
  const dLon = toRadians(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRadians(lat1)) *
      Math.cos(toRadians(lat2)) *
      Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return EARTH_RADIUS_MILES * c;
}
