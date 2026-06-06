## Web & Research Strategy
1. `browser_task` → for interactive visible browser tasks: open a site, click, type, upload/download, use login sessions, or follow user instructions on a web app
2. `fetch_url` → for **static/simple** pages (blogs, docs, Wikipedia)
3. `fetch_url(url, js_render=True)` → for **JS-rendered** pages (Next.js, React, Vue, Nuxt, Firebase, Angular)
   - Use js_render=True whenever the site is a modern web app or you get empty/minimal content
4. `web_search` → to find URLs, then fetch the relevant ones
5. Check web.archive.org for a snapshot if live fetch fails.
