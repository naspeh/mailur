**alpha state :: [more info][info] :: [public demo][demo] :: [short video][video]**

[info]: https://pusto.org/mailur/
[demo]: http://mail.pusto.org
[video]: https://vimeo.com/145416826

Mailur aims to become the future open source replacement for Gmail.

It is already usable as an alternative Gmail interface with a set of unique features:
- internal lightweight tabs
- linking few threads together
- composing emails with [Markdown][]

[Markdown]: https://daringfireball.net/projects/markdown/syntax

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

#### Run locally
The simplest way is running docker container.

```bash
> docker run -d -p 80 --name=mailur naspeh/mailur
```

Then, open http://localhost in your browser.

For manual installation look at [deploy folder](https://github.com/naspeh/mailur/tree/master/deploy) and [manage.py: deploy](https://github.com/naspeh/mailur/blob/master/manage.py#L302), these files are used for deploying to docker container.

##### Dependencies:
- PostgreSQL 9.4
- Python >= 3.4
- `./manage.py reqs -t frozen` or `pip install -r requirements.txt`
- `npm install`
- 2 gunicorn workers for main server and websocket server
- nginx to proxy gunicorn workers and serve static folder with frontend
- cron for running synchronization like [here](https://github.com/naspeh/mailur/blob/master/deploy/fcrontab)

**Contributions are welcome.**

![Screenshots](https://pusto.org/mailur/alpha/screenshots.gif)

I will update docs somehow...
