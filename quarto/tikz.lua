--[[
  tikz.lua — render TikZ code blocks to accessible figures (SVG for HTML,
  vector for PDF), with required alt text and an optional visible description.

    ```{.circuitikz alt="..."}   classical logic circuits (AND/OR/NAND/NOT)
    ```{.quantikz alt="..."}     standard horizontal quantum circuit notation
    ```{.tikz alt="..."}         anything else

  Attributes:
    alt="..."       REQUIRED. There is no state to generate a description from,
                    so it has to be written. A diagram with no alt text is an
                    error rather than a silent accessibility hole. At most 120
                    characters: YuJa Panorama marks longer alt text as a severe
                    issue, and screen readers cannot pause inside it.
    desc="..."      the full description, printed as a paragraph under the
                    figure ("Figure description. ..."). Use it whenever the
                    diagram carries more than a short alt can say. Visible
                    text serves everyone, not only screen-reader users.
    width="60%"     display width
    preamble="..."  extra LaTeX preamble lines for this one figure

  Compiling LaTeX per figure is slow, so tools/tikz.py content-addresses the
  output and only recompiles what changed.
]]

local TOOLS_DIR = PANDOC_SCRIPT_FILE:match('^(.*)[/\\][^/\\]+$') or '.'
local PROJECT_DIR = TOOLS_DIR:match('^(.*)[/\\][^/\\]+$') or '.'
local TIKZ_SCRIPT = TOOLS_DIR .. '/tikz.py'
local FIG_DIR = PROJECT_DIR .. '/figures'

local LIBRARIES = { tikz = true, circuitikz = true, quantikz = true }

local json_decode = (quarto and quarto.json and quarto.json.decode)
  or (pandoc.json and pandoc.json.decode)

local function is_latex()
  if quarto and quarto.doc and quarto.doc.is_format then
    return quarto.doc.is_format('latex') or quarto.doc.is_format('pdf')
  end
  return FORMAT ~= nil and FORMAT:match('latex') ~= nil
end

local function render_tikz(source, library, preamble)
  local args = { '--outdir', FIG_DIR, '--library', library }
  if preamble and preamble ~= '' then
    args[#args + 1] = '--preamble'
    args[#args + 1] = preamble
  end
  local out = pandoc.pipe(TIKZ_SCRIPT, args, source)
  local info = json_decode(out)
  if type(info) ~= 'table' or not info.file then
    error('tikz.py returned no figure for source:\n' .. source .. '\ngot: ' .. tostring(out))
  end
  return info
end

-- Escape the LaTeX-special characters that could appear in alt text so it is
-- safe inside \includegraphics[alt={…}].
local function latex_escape(s)
  return (s:gsub('([{}%%#&_$])', '\\%1'))
end

-- Quarto logs a Lua error() and carries on, exiting 0 with the figure
-- missing or wrong, so a broken accessibility rule would pass unnoticed.
-- Stop the render instead.
local function fail(msg)
  io.stderr:write('tikz.lua: ' .. msg .. '\n')
  os.exit(1)
end

function CodeBlock(el)
  local library = nil
  for name in pairs(LIBRARIES) do
    if el.classes:includes(name) then library = name end
  end
  if not library then return nil end

  local alt = el.attributes['alt']
  if not alt or alt == '' then
    fail(
      'a ' .. library .. ' diagram has no alt="…".\n' ..
      'These cannot be described automatically, so the description has to be ' ..
      'written by hand. Source was:\n' .. el.text
    )
  end
  if utf8.len(alt) > 120 then
    fail(
      'a ' .. library .. ' diagram has alt text of ' .. utf8.len(alt) ..
      ' characters; the limit is 120. Keep alt="…" to a short label and ' ..
      'move the full description to desc="…". Alt was:\n' .. alt
    )
  end
  local desc = el.attributes['desc']
  local desc_para = nil
  if desc and desc ~= '' then
    local parsed = pandoc.read(desc, 'markdown').blocks
    local inlines = { pandoc.Strong({ pandoc.Str('Figure'), pandoc.Space(),
      pandoc.Str('description.') }), pandoc.Space() }
    if parsed[1] and parsed[1].content then
      for _, x in ipairs(parsed[1].content) do inlines[#inlines + 1] = x end
    end
    desc_para = pandoc.Para(inlines)
  end

  local ok, info = pcall(render_tikz, el.text, library, el.attributes['preamble'])
  if not ok then
    error('tikz diagram failed to render:\n' .. el.text .. '\n' .. tostring(info))
  end

  local img_attrs = { ['fig-alt'] = alt, ['fig-align'] = 'center' }
  if el.attributes['width'] then img_attrs['width'] = el.attributes['width'] end

  -- PDF: embed the figure PDF directly so it keeps real /Alt text. Quarto drops
  -- fig-alt on the LaTeX path, so we bypass its image pipeline exactly as the
  -- misty filter does.
  if is_latex() and info.pdf then
    local raw = '\\begin{center}\\pandocbounded{\\includegraphics[alt={'
      .. latex_escape(alt) .. '},keepaspectratio]{' .. info.pdf .. '}}\\end{center}'
    return { pandoc.RawBlock('latex', raw), desc_para }
  end

  local src = '/figures/' .. info.file:match('[^/]+$')
  local img = pandoc.Image({}, src, '', pandoc.Attr('', {}, img_attrs))
  return { pandoc.Para({ img }), desc_para }
end

return { { CodeBlock = CodeBlock } }
