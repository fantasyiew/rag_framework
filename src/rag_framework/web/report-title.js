export function reportTitle(report) {
  return report.name?.trim() || `${report.kind.toUpperCase()} 评估结果`;
}
