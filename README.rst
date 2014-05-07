Namail
======

**Namail** is an Open Source webmail client with Gmail-like conversations.

*The first name was Mailr, but it was taken for similar project on Ruby.*

**More information:** http://pusto.org/en/mailr/

**Public demo:** http://mail.pusto.org

You can send emails to **mailr[at]pusto.org** for them to appear in the Inbox.

*Namail is early in development. Lots of work still has to be done.*


Screenshot
----------
.. image:: http://pusto.org/en/mailr/screenshot-one.png

.. image:: http://pusto.org/en/mailr/screenshot-s.png

Installation
------------

Requires **Python>=3.3** and **PostgreSQL**.

.. code:: sql

    # Create database with hstore extension
    CREATE DATABASE namail WITH OWNER namail;
    CREATE EXTENSION hstore;

.. code:: bash

    $ pip install -r requiremets.txt

    $ cp conf_test.json conf.json
    # Then fix "email" and "pg_*" settings

    $ ./manage.py db-init

Then you have two way for gmail authorization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Via OAuth (preferred):
    Go to https://console.developers.google.com/ and create new client id
      - host: http://localhost
      - redirect uri: http://localhost:5000/auth-callback/

    Fill ``"google_id"``, ``"google_secret"`` fields in config file

    .. code:: bash

        $ ./manage.py run -w

    Go to http://localhost:5000/auth/ to get an auth token from Google

Or just fill a ``"password"`` field in config file (more simple for trying)

Synchronize emails
~~~~~~~~~~~~~~~~~~
.. code:: bash

    # Then synchronize all emails
    $ ./manage.py sync -b

    # Then you can see your emails in Namail
    $ ./manage.py run -w
