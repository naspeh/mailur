**alpha state :: [more info][] :: [public demo][] :: [short video][]**

[more info]: https://pusto.org/mailur/
[public demo]: http://mail.pusto.org
[short video]: https://vimeo.com/145416826

Mailur aims to become the future open source replacement for Gmail.

It is already usable as an alternative Gmail interface with a set of unique features:
- internal lightweight tabs
- linking few threads together
- composing emails with [Markdown][]

[Markdown]: https://daringfireball.net/projects/markdown/syntax

![Screenshots](https://pusto.org/mailur/alpha/screenshots.gif)
**Backend.** Python3. Main JSON-RPC server and WebSocket server for push notifications (with help of [Werkzeug][], [psycopg2][], [aiohttp][], [lxml][]).

[Werkzeug]: http://werkzeug.pocoo.org/
[psycopg2]: http://initd.org/psycopg/
[aiohttp]: http://aiohttp.readthedocs.org/
[lxml]: http://lxml.de/

**Frontend.** [ES6][]. Single-page application based on [vuejs][]. Also it used [less][] as CSS preprocessor and [browserify][] for bundling up all dependencies.

[es6]: http://www.ecma-international.org/ecma-262/6.0/
[vuejs]: http://vuejs.org/
[less]: http://lesscss.org/
[browserify]: http://browserify.org/

**Run locally.** The best way is running docker container.

```bash
> docker run -d -p 80 --name=mailur naspeh/mailur
```

Then, open http://localhost in your browser.
