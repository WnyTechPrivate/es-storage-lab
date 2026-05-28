"""Build HTML report from measurements.csv."""
import csv
import json
from config import RESULT_DIR

CSV_PATH  = RESULT_DIR / "measurements.csv"
HTML_PATH = RESULT_DIR / "report.html"


def parse_case(case):
    if case == "baseline":
        return dict(mode="-", source="-", codec="-", index="-", doc_values="-", parsing="-")
    parts = case.split(".")
    return dict(
        mode=parts[0], source=parts[1], codec=parts[2],
        index=parts[3], doc_values=parts[4], parsing=parts[5],
    )


def load_rows():
    out = []
    with CSV_PATH.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k in r:
                if k in ("case", "datastream", "backing_index"):
                    continue
                try:
                    r[k] = float(r[k]) if "." in r[k] else int(r[k])
                except Exception:
                    pass
            r.update(parse_case(r["case"]))
            out.append(r)
    return out


HTML_TMPL = """<!doctype html>
<html><head><meta charset="utf-8">
<title>ES Storage Matrix Report</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body { font-family: -apple-system, Segoe UI, sans-serif; margin: 20px; }
  h2 { margin-top: 32px; }
  table { border-collapse: collapse; font-size: 12px; width: 100%; }
  th, td { border: 1px solid #ddd; padding: 4px 6px; text-align: right; }
  th { background: #f5f5f5; cursor: pointer; }
  td.case, th.case { text-align: left; font-family: ui-monospace, monospace; }
  tr:hover { background: #f9f9f9; }
  .chart { height: 480px; margin: 16px 0; }
  .summary { background: #f0f6ff; padding: 12px 16px; border-radius: 6px; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 10px; background: #eef; margin-right: 4px; font-size: 11px; }
</style>
</head>
<body>
<h1>Elasticsearch 저장 효율 매트릭스</h1>
<div class="summary">
  <div><b>Docs/case:</b> <span id="docs"></span></div>
  <div><b>Raw input:</b> <span id="raw"></span> bytes</div>
  <div><b>Cases measured:</b> <span id="ncase"></span></div>
  <div style="margin-top:8px;font-size:12px;color:#555">
    <span class="pill">mode: std=standard, ldb=logsdb</span>
    <span class="pill">source: str=stored, syn=synthetic</span>
    <span class="pill">codec: lz4=default, zstd=best_compression</span>
    <span class="pill">index/dv: it/dt=true, if/df=false</span>
    <span class="pill">parsing: p1=raw, p2=parsed+raw, p3=parsed-only</span>
  </div>
</div>

<h2>1. Primary store size (% of raw)</h2>
<div id="chart_ratio" class="chart"></div>

<h2>2. Component breakdown — top 32 smallest cases</h2>
<div id="chart_stack" class="chart"></div>

<h2>3. By dimension — average ratio</h2>
<div id="chart_dim" class="chart"></div>

<h2>4. Full table (click headers to sort)</h2>
<div id="tablewrap"></div>

<script>
const ROWS = __ROWS__;
const RAW  = __RAW__;
const DOCS = __DOCS__;

document.getElementById("docs").textContent = DOCS;
document.getElementById("raw").textContent = RAW.toLocaleString();
document.getElementById("ncase").textContent = ROWS.length;

function fmt(b) { return (b/1024/1024).toFixed(2) + " MB"; }
function pct(x) { return (x*100).toFixed(1) + "%"; }

const byRatio = [...ROWS].sort((a,b) => a.ratio_pri_over_raw - b.ratio_pri_over_raw);
Plotly.newPlot("chart_ratio", [{
  type: "bar",
  x: byRatio.map(r => r.case),
  y: byRatio.map(r => r.ratio_pri_over_raw*100),
  text: byRatio.map(r => (r.ratio_pri_over_raw*100).toFixed(1)+"%"),
  textposition: "outside",
  marker: { color: byRatio.map(r => r.parsing==="p1"?"#9eb7e5":r.parsing==="p2"?"#e58c8c":"#8ce5b5") }
}], { yaxis: {title:"pri.store / raw (%)"}, xaxis:{tickangle:-60, tickfont:{size:9}}, margin:{b:140} });

const stack = byRatio.slice(0,32);
const fields = ["inverted_index_b","doc_values_b","stored_fields_b","points_b","ignored_source_b","norms_b"];
const colors = {"inverted_index_b":"#5b8def","doc_values_b":"#f1a93b","stored_fields_b":"#e35d6a","points_b":"#7ec77b","ignored_source_b":"#a06cd5","norms_b":"#777"};
Plotly.newPlot("chart_stack",
  fields.map(f => ({
    type:"bar", name: f.replace("_b",""),
    x: stack.map(r => r.case),
    y: stack.map(r => r[f]/1024/1024),
    marker:{color: colors[f]}
  })),
  { barmode:"stack", yaxis:{title:"MB"}, xaxis:{tickangle:-60, tickfont:{size:9}}, margin:{b:140} }
);

function avgBy(key) {
  const m = {};
  ROWS.filter(r => r.case !== "baseline").forEach(r => {
    const k = r[key];
    (m[k] ||= []).push(r.ratio_pri_over_raw);
  });
  return Object.entries(m).map(([k,v]) => ({k, avg:v.reduce((a,b)=>a+b,0)/v.length}));
}
const dims = ["parsing","mode","source","codec","index","doc_values"];
Plotly.newPlot("chart_dim",
  dims.map(d => {
    const a = avgBy(d);
    return { type:"bar", name:d, x:a.map(x=>d+"="+x.k), y:a.map(x=>x.avg*100) };
  }),
  { yaxis:{title:"avg pri/raw (%)"}, xaxis:{tickangle:-45, tickfont:{size:10}}, margin:{b:120} }
);

const cols = Object.keys(ROWS[0]);
let html = "<table id='tbl'><thead><tr>" + cols.map((c,i)=>`<th data-col='${i}' class='${i===0?'case':''}'>${c}</th>`).join("") + "</tr></thead><tbody>";
ROWS.forEach(r => {
  html += "<tr>" + cols.map((c,i)=>`<td class='${i===0?'case':''}'>${r[c]}</td>`).join("") + "</tr>";
});
html += "</tbody></table>";
document.getElementById("tablewrap").innerHTML = html;
document.querySelectorAll("#tbl th").forEach(th => {
  th.onclick = () => {
    const col = +th.dataset.col;
    const tb = th.closest("table").tBodies[0];
    const rows = [...tb.rows];
    const asc = th.dataset.asc !== "1";
    rows.sort((a,b) => {
      const x = a.cells[col].textContent, y = b.cells[col].textContent;
      const nx = parseFloat(x), ny = parseFloat(y);
      const isNum = !isNaN(nx) && !isNaN(ny);
      return asc ? (isNum ? nx-ny : x.localeCompare(y)) : (isNum ? ny-nx : y.localeCompare(x));
    });
    th.dataset.asc = asc ? "1" : "0";
    rows.forEach(r => tb.appendChild(r));
  };
});
</script>
</body></html>
"""


def main():
    rows = load_rows()
    raw = int(rows[0]["raw_bytes"]) if rows else 0
    docs_per = max((r["docs"] for r in rows if r["case"] != "baseline"), default=0)
    html = (HTML_TMPL
            .replace("__ROWS__", json.dumps(rows, ensure_ascii=False))
            .replace("__RAW__", str(raw))
            .replace("__DOCS__", str(docs_per)))
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"wrote {HTML_PATH}")


if __name__ == "__main__":
    main()
