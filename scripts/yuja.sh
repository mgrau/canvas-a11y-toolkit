#!/bin/zsh
# yuja.sh list <outdir>                 every scanned item with its score
# yuja.sh report <search text> <outdir> one item's issues
# yuja.sh issues <outdir>               issues of every web page under 100
#
# Reads YuJa Panorama's accessibility report (the Canvas external tool in
# course.toml [panorama] tool_id) as the token's owner, with no browser
# login: Canvas makes a one-time launch link, which headless Chrome opens
# (scripts/yuja_launch.mjs). It only reads. It never clicks Reprocess or
# anything else that changes Panorama. Every JSON response is saved in <outdir>; `list` also prints a table
# (scripts/yuja_table.py). getPaginatedCourseDocuments has each item's score,
# getFileIssues the opened item's issues. The responses name the instructor
# and carry session tokens, so write them under the gitignored _notes/,
# never into the repo.
#
# Panorama scans a new file within minutes and a new page within about a
# quarter of an hour; until then a search finds nothing ("found":0).
SP=${0:A:h}
if [[ $# -lt 2 && $1 != (list|issues) ]] || [[ $# -lt 1 ]]; then
  sed -n '2,4p' $0; exit 2
fi
launch=$(uv run --quiet --script $SP/yuja_table.py --launch) || exit 1
course=${launch%% *}
url=${launch#* }
mode=$1; shift
if [[ $mode == (list|issues) ]]; then search=''; out=$1; else search=$1; out=$2; fi
docs_js="
  const body = {identifierKey: new URLSearchParams(location.search).get('institution'), contextId: '$course', page: 1,
    searchText: ${(qqq)search}, pageSize: 200, sortColumnName: 'score', sortOrder: 'asc', fileTypeFilter: [],
    reportGeneratedFilter: [], startYear: 2020, startMonth: 1, endYear: 2040, endMonth: 12, minScore: null, maxScore: null};
  const r = await fetch('/api/document/getPaginatedCourseDocuments', {method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const found = await r.json();
  const docs = found.documents || [];"
if [[ $mode == list ]]; then
  node $SP/yuja_launch.mjs "$url" $out 25 "(async () => { $docs_js return {found: docs.length}; })()" 5 || exit 1
  uv run --quiet --script $SP/yuja_table.py $out
  exit
fi
# Opening a file's report (Files & Issues, search, the row's menu, View) is
# the only way to get the session token getFileIssues needs.
open_js="
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  async function openReport(name) {
    [...document.querySelectorAll('button')].find(e => e.innerText.trim() === 'Files & Issues').click();
    await sleep(6000);
    const input = [...document.querySelectorAll('input')].find(i => /search/i.test(i.placeholder + i.getAttribute('aria-label') + i.type));
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, name);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    await sleep(500);
    // Enter stopped running the search (Nov 2026); the button does.
    [...document.querySelectorAll('button')].find(e => e.innerText.trim() === 'Search')?.click();
    await sleep(6000);
    const row = [...document.querySelectorAll('tr')].find(tr => tr.innerText.includes(name));
    if (!row) return 'row not shown';
    row.querySelector('button').click();
    await sleep(1500);
    const view = [...document.querySelectorAll('[role=menuitem],li,button,a')].filter(e => e.innerText && e.innerText.trim() === 'View');
    if (view.length !== 1) return 'View items: ' + view.length;
    view[0].click();
    return 'opened';
  }"
if [[ $mode == issues ]]; then
  # The report viewer runs in a frame the page cannot reach, so open one
  # report, keep its getFileIssues request (requests.json), and replay it
  # from Python for every web page under 100.
  action="(async () => {
$open_js
$docs_js
  const pages = docs.filter(d => d.format !== 'pdf' && d.score < 100);
  if (!pages.length) return {pages: 0};
  return {view: await openReport(pages[0].displayName), pages};
})()"
  node $SP/yuja_launch.mjs "$url" $out 25 "$action" 20 || exit 1
  uv run --quiet --script $SP/yuja_table.py --issues $out
  exit
fi
action="(async () => {
$open_js
$docs_js
  if (!docs.length) return {found: 0, status: r.status};
  return {found: docs.length, docs, view: await openReport(docs[0].displayName)};
})()"
node $SP/yuja_launch.mjs "$url" $out 25 "$action" 25
