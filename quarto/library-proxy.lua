--[[
  library-proxy.lua — send DOI links through the school library's proxy.

  Many journal articles are behind a paywall. Off campus, a plain
  https://doi.org/... link shows students the publisher's paywall; the same
  link behind the library's EZproxy asks for their campus login first, then
  opens the article on the school's subscription. Write the plain DOI in the
  source (it is the readable, citable form) and this filter adds the prefix
  when rendering.

    [Title](https://doi.org/10.1119/1.4901236)
      -> https://login.proxy.lib.example.edu/login?url=https://doi.org/10.1119/1.4901236

  The prefix comes from `library-proxy: "<prefix>"` in _quarto.yml, which
  new_course.py writes from course.toml [library] proxy_prefix. With no
  prefix the filter does nothing. A document can switch it off with
  `library-proxy: false` (an open-access article, or a page for readers
  outside the school). scripts/modules.py applies the same prefix to module
  links.
]]

local PREFIX = nil

local function proxied(url)
  if url:match('^https?://doi%.org/') or url:match('^https?://dx%.doi%.org/') then
    return PREFIX .. url
  end
  return nil
end

function Meta(meta)
  local v = meta['library-proxy']
  if v == false then
    PREFIX = nil
  elseif v ~= nil and v ~= true then
    local s = pandoc.utils.stringify(v)
    PREFIX = (s ~= '' and s) or nil
  end
end

function Link(el)
  if not PREFIX then return nil end
  local url = proxied(el.target)
  if url then
    el.target = url
    return el
  end
end

return { { Meta = Meta }, { Link = Link } }
