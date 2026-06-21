/**
 * 净值曲线 SVG path 推导（模拟台运行盘 + PaperBoardCard 共用）。
 * 对齐 模拟台.dc.html `_svgLine` / PaperBoard.dc.html renderVals 的几何语义：
 *   分段绘制（回测段 [0,splitX] / 实盘段 [splitX,w]），y 轴按全序列 lo/hi 归一。
 * 纯数学、零色值——色由调用方用 --desk-* token 上。
 */

/** 把序列映射成 SVG path（M/L 折线）。x 在 [x0,x1] 区间均分。 */
export function svgLine(
  arr: number[],
  w: number,
  h: number,
  lo: number,
  hi: number,
  pad: number,
  x0: number,
  x1: number,
): string {
  const n = arr.length;
  const span = hi - lo || 1;
  if (n === 0) return "";
  const denom = n > 1 ? n - 1 : 1;
  return arr
    .map((v, i) => {
      const x = x0 + (i / denom) * (x1 - x0);
      const y = h - pad - ((v - lo) / span) * (h - 2 * pad);
      return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

/** 确定性伪随机（同 DC `_nz`：可复现 mock，不引入真随机）。 */
export function nz(i: number): number {
  const x = Math.sin(i * 12.9898 + 3.7) * 43758.5453;
  return x - Math.floor(x);
}

export interface EquityPaths {
  histPath: string;
  paperPath: string;
  paperArea: string;
  benchPath: string;
  splitX: number;
}

/**
 * 由回测段/实盘段/基准三序列生成全套 path。
 * w/h = SVG viewBox 尺寸；pad = 上下留白。
 */
export function buildEquityPaths(
  hist: number[],
  paper: number[],
  bench: number[],
  w: number,
  h: number,
  pad: number,
  histN: number,
  allN: number,
): EquityPaths {
  const all = [...hist, ...paper, ...bench];
  const lo = all.length ? Math.min(...all) : 0;
  const hi = all.length ? Math.max(...all) : 1;
  const splitX = allN > 1 ? (histN / (allN - 1)) * w : 0;
  const histPath = svgLine(hist, w, h, lo, hi, pad, 0, splitX);
  const paperPath = svgLine(paper, w, h, lo, hi, pad, splitX, w);
  const benchPath = svgLine(bench, w, h, lo, hi, pad, 0, w);
  const yBot = h - pad;
  const paperArea = paperPath
    ? `${paperPath} L${w} ${yBot} L${splitX.toFixed(1)} ${yBot} Z`
    : "";
  return { histPath, paperPath, paperArea, benchPath, splitX };
}
