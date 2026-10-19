/** Resolve report files beneath the application's route basename. */
export function reportBasePath(routeBase: string): string {
  return `${routeBase.replace(/\/+$/, "")}/reports/`;
}
