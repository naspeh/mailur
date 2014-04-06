##Mailr

**Mailr** is an Open Source webmail client with gmail like conversations.

**More information**: http://pusto.org/en/mailr/

**Public demo**: http://mail.pusto.org

You can send emails to **mailr[at]pusto.org** for them to appear in the Inbox.

_Mailr is early in development. Lots of work still has to be done._

###Screenshot

![Mailr Screenshot](http://pusto.org/en/mailr/screenshot-s.png)

###Installation

Requires Python>=3.3 and PostgreSQL.

```bash
$ pip install -r requiremets.txt
```

```sql
# Create database with hstore extension
> CREATE DATABASE mailr WITH OWNER mailr;
> CREATE EXTENSION hstore;
```

```bash
$ ./manage.py db-init

$ cp conf_test.json conf.json
# Then fix "google_id", "google_secret", "email" and "pg_*" settings

$ ./manage.py run
# Go to http://localhost:5000/auth/ to get an auth token from Google

# Then synchronize all emails
$ ./manage.py sync -b

# Then you can see your emails in Mailr
$ ./manage.py run
```
