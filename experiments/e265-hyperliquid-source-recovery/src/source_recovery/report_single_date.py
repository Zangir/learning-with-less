"""Render the E270 source-only report and its editable coverage figure."""
from settings import BASE, NS, bind, now, pin, read, save
from single_date_source import OUT, stamp
from datetime import datetime, timezone
import csv
import shutil
import subprocess
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def utc(ns):
    return datetime.fromtimestamp(ns//NS,timezone.utc).strftime("%H:%M:%S")+f".{ns%NS//1_000_000:03d}"


def main():
    pin()
    s = read(OUT/"source_validation.json")
    v = read(OUT/"producer_verification.json")
    d = read(OUT/"source-request-declaration.json")
    resource = read(OUT/"resource-preflight.json")
    hours = {h:dict(hour_utc=h,cuts=0,supported=0,unsupported=0) for h in range(24)}
    with (OUT/"BTC/grid_audit.csv").open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            h = datetime.fromtimestamp(int(row["cut_ns"])//NS,timezone.utc).hour
            hours[h]["cuts"] += 1
            hours[h]["supported" if row["supported"]=="True" else "unsupported"] += 1
    with (OUT/"coverage_by_hour.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(hours[0]));writer.writeheader();writer.writerows(hours.values())
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False,"svg.fonttype":"none"})
    fig,ax=plt.subplots(figsize=(9,2.8),layout="constrained")
    ax.bar(range(24),[h["unsupported"] for h in hours.values()],color="#a65f32",width=.7)
    ax.set_xticks(range(24));ax.set_xlabel("UTC hour on 1 February 2026")
    ax.set_ylabel("Unsupported one-second cuts")
    ax.set_title("Source gaps remain visible in the declared full-day cohort",loc="left",fontweight="bold")
    ax.grid(axis="y",alpha=.2);ax.set_axisbelow(True)
    fig.savefig(OUT/"main_figure.png",dpi=180);fig.savefig(OUT/"main_figure.svg");plt.close(fig)
    retained = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    budget = dict(at=now(),continued_charged_transfer_bytes=2254224507,new_network_charge_bytes=0,
        cumulative_charged_transfer_bytes=2254224507,continued_retained_upper_bound_bytes=11805294767,
        new_retained_bytes_at_report=retained,report_and_seal_reserve_bytes=8*1024**2,
        projected_cumulative_retained_bytes=11805294767+retained+8*1024**2,
        q16_reserved_bytes=512*1024**2,free_C_bytes=shutil.disk_usage(OUT).free)
    assert retained+8*1024**2 <= 256*1024**2
    assert budget["projected_cumulative_retained_bytes"]+budget["q16_reserved_bytes"]<=12*1024**3
    save(OUT/"resource-at-report.json",budget)
    report=r"""\documentclass[10pt]{article}
\usepackage[a4paper,margin=20mm]{geometry}
\usepackage{fontspec}\setmainfont{TeX Gyre Pagella}
\usepackage{graphicx,booktabs,array,microtype}
\usepackage[hidelinks]{hyperref}
\setlength{\parindent}{0pt}\setlength{\parskip}{5pt}\setlength{\emergencystretch}{2em}
\title{\vspace{-12mm}\Large A fixed-date Hyperliquid BTC sampled-L2 source supply}
\author{T018 / E270 --- D054 source engineering outcome}\date{22 September 2026}
\begin{document}\maketitle
\textbf{Outcome.} The declared 1 February 2026 BTC source passes producer validation and is ready for a separate exact-source review. No strategy execution is authorized by this packet. The result concerns source availability, ordering and reproducibility; it does not evaluate the C/P/R persistence claim or assert a market-effect finding.

\section{Request and source lineage}
The candidate was fixed by D054 as the next calendar-first-day after excluded January 2026. The closed E269 preparation retains its null selection and disabled execution state. December exclusions and the failed January source remain unchanged. There is one candidate, with no replacement date, partial-day alternative or outcome-based window selection.

The full provider receipt day had already been acquired by T018 for a Q18 source handoff: 144 consecutive ten-minute HTTP partitions, with 64,880,639 compressed bytes. E270 reuses those immutable bytes in place and transfers zero new market bytes. The original requests name \texttt{api.tardis.dev/v1/data-feeds/hyperliquid}, \texttt{l2Book}, BTC and ETH, UTC midnight, offsets 0--1430, ten-minute slices and gzip compression. The shared raw files contain both symbols; only BTC is supplied to this cohort. Every request/response partition and both compressed and decoded hashes were reverified, including gzip CRCs. This establishes correspondence to retained provider responses, not independent exchange authentication, calibrated latency or lossless capture.

\section{Unchanged source policy and observed support}
The exact inherited T008 startup30 normalizer first excludes receipts earlier than UTC 00:00:30. It then validates remaining source order and full-depth equal-time payloads before event-window filtering. Conflicting ties and inversions reject the source; identical full-payload ties collapse only in the event-time state stream and remain in provenance and the duplicate ledger. No sorting, interpolation, padding or state from the excluded prefix is used.

The normalized event window remains [00:00:30,24:00:00). Full native depth is checked before projecting five levels, with exact positive integer prices/sizes at scale $10^8$, positive counts and an uncrossed BBO. Blank disconnects and event gaps strictly exceeding two seconds delimit segments. Segment support ends at the last actual observation plus one nanosecond; a one-second grid uses past-only as-of quotes aged at most 1.5 seconds.

\begin{center}\begin{tabular}{@{}lr@{}}\toprule
Source check & Observed value\\\midrule
Unique BTC states / retained receipt rows & 156,889 / 156,899\\
Identical duplicate receipts / BTC startup exclusions & 10 / 5\\
Source segments / gaps exceeding two seconds & 15 / 14\\
Raw disconnect markers / minimum observed depth per side & 16 / 20\\
Supported / unsupported one-second cuts & 86,056 / 314\\
Actual first / last exchange-time observation & __FIRST__ / __LAST__\\
\bottomrule\end{tabular}\end{center}
The requested full-day archive scope is distinct from complete observation at every cut. The initial missing support and every interior gap remain visible; no favorable interval is substituted.

\newpage
\begin{figure}[!h]\centering\includegraphics[width=\linewidth]{main_figure.png}
\caption{Unsupported source-grid cuts by UTC hour. These are observation-support diagnostics, not strategy censoring, labels or scores. All 314 unsupported cuts lie outside actual segment endpoints; no in-segment grid cut exceeds the 1.5-second age limit.}\end{figure}

\section{Verification, exposure and review boundary}
Producer verification compares every exported top-five price, size and count against the earlier independent string-arithmetic parser, whereas the inherited normalizer uses Decimal arithmetic. All 156,889 rows agree. Receipt/provenance membership, all ten duplicate dispositions and all fifteen segment boundaries reconcile. An independent vectorized as-of calculation agrees on all 86,370 declared grid cuts. Synthetic boundary fixtures check exclusion-before-ordering, full-depth conflicts beyond level five, duplicate disposition and exact freshness/gap thresholds.

This date is not a pristine holdout. Its native BBO appears in the separate Q17 adaptation. Its sampled-L2 bytes were previously downloaded and normalized for the Q18 source supply, with prior source-quality diagnostics and the RV035 source-field audit known. Global strategy-evaluation exposure beyond the supplied scoped statement remains unknown. No strategy labels, fitted models, scalers, inference, scores, fits or solvers were loaded or computed during E270. The completed Q17/Q18 adaptations remain intact.

The new contract binds E270's explicit source identifier, normalized rows, receipts, source segments, request declaration and inherited code. The identifier is supplied as the existing consumer loader's source-id argument; physical field definitions and source policies are unchanged. Gates A1--A4 require independent review of this exact packet and its exposure qualification. Gate A5 requires a later explicit coordinator execution release; A6 belongs to that future empirical audit. The producer grants neither gate.

\section{Resources, reproducibility and primary priority}
Actual retained-byte reconciliation covered canonical T008 r2--r4 and T018 r1--r2: __ACTUAL__ bytes, below the continued upper bound of 11,805,294,767 bytes. Previous reserves and transfer charges were carried forward. New network charge is zero; cumulative charged transfer remains 2,254,224,507 bytes. New E270 retained data at report generation is __NEW__ MiB. Including an 8 MiB finalization reserve, cumulative retention is projected at __CUM__ GiB; a further 512 MiB remains reserved for Q16 under the 12 GiB cap. C: has __FREE__ GiB free, above the 50 GiB minimum.

Normalization took __NORM__ seconds and producer verification __VERIFY__ seconds. Peak normalization working set was __RAM__ GiB. The jobs used logical CPUs 0 and 1, an 8 GiB memory cap, seed 20260919 and one-hour detached tmux limits. No new infrastructure or paid acquisition was used. The editable figure, hourly table, raw-source bindings, exact scripts, ledgers, terminal receipts and hashes accompany this report.

Q16 remains the primary research path. Its exact D046 source checkpoint and resource receipt are preserved; no Mac reconnection or repeated path request occurred. A concrete native archive path would take priority over this secondary operation. The source-only E270 outcome does not close Q16 or endorse an ICLR contribution.
\end{document}
"""
    replacements={"__FIRST__":utc(s["first_event_ns"]),"__LAST__":utc(s["last_event_ns"]),
        "__ACTUAL__":f"{resource['actual_canonical_retained_bytes']:,}","__NEW__":f"{retained/1024**2:.2f}",
        "__CUM__":f"{budget['projected_cumulative_retained_bytes']/1024**3:.3f}","__FREE__":f"{budget['free_C_bytes']/1024**3:.1f}",
        "__NORM__":f"{read(OUT/'normalization_terminal.json')['elapsed_seconds']:.2f}","__VERIFY__":f"{v['elapsed_seconds']:.2f}",
        "__RAM__":f"{s['peak_working_set_bytes']/1024**3:.2f}"}
    for key,value in replacements.items():report=report.replace(key,value)
    (OUT/"report.tex").write_text(report,encoding="utf-8")
    for _ in range(2):
        result=subprocess.run([shutil.which("xelatex"),"-disable-installer","-interaction=nonstopmode","-halt-on-error","report.tex"],cwd=OUT,capture_output=True,text=True)
        with (OUT/"logs/report-compile.log").open("a",encoding="utf-8") as stream:stream.write(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError("Report compilation failed")
    previews=OUT/"rendered";previews.mkdir(exist_ok=True)
    subprocess.run([shutil.which("pdftoppm"),"-r","110","-png",str(OUT/"report.pdf"),str(previews/"page")],check=True)
    save(OUT/"report-build.json",dict(at=now(),pdf=bind(OUT/"report.pdf"),tex=bind(OUT/"report.tex"),
        overfull_boxes=(OUT/"report.log").read_text(errors="replace").count("Overfull"),pages=[bind(p) for p in previews.glob('*.png')],visual_inspection="pending"))
    stamp("E270 source report compiled twice with XeLaTeX and rendered for visual inspection")


if __name__ == "__main__":
    main()
