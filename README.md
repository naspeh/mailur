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

```sql
# Create database with hstore extension
> CREATE DATABASE mailr WITH OWNER mailr;
> CREATE EXTENSION hstore;
```

```bash
$ pip install -r requiremets.txt

$ cp conf_test.json conf.json
# Then fix "email" and "pg_*" settings

$ ./manage.py db-init
```

#### Then you have two way for authorization to gmail
1. Via OAuth (preferred)
    Go to https://console.developers.google.com/ and create new client id
    - host: "http://localhost"
    - redirect uri: "http://localhost:5000/auth-callback/"

    Fill `"google_id"`, `"google_secret"` fields in config file

    ```bash
    $ ./manage.py run -w
    ```

    Go to `http://localhost:5000/auth/` to get an auth token from Google

2. Or just fill a "password" field in config file (more simple for trying)

```bash
# Then synchronize all emails
$ ./manage.py sync -b

# Then you can see your emails in Mailr
$ ./manage.py run -w
```
