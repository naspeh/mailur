{% macro gravatars(addrs, size=16) %}
    {% for addr in addrs %}
        <img src="{{ addr|get_gravatar(size) }}"
            height="{{ size }}" width="{{ size }}"
            alt="{{ addr|e }}" title="{{ addr|e }}"/>
    {% endfor %}
{% endmacro %}

{% macro render(emails, thread=False, show=False, counts={}, max_count=50) %}
<ul class="emails">
{% for email in emails %}
    <li class="email
            {% if email.unread %} email-unread{% endif %}
            {% if show %} email-showed{% endif %}
            {% if loop.index > max_count %} email-hide{% endif %}
        "
        data-id="{{ email.uid }}"
        data-labels="{{ email.labels.keys()|map('int')|list }}"
        data-thread="{{ url_for('gm_thread', id=email.gm_thrid) }}"
    >
        <ul class="email-line">
            <li class="email-pick">
                <input type="checkbox" name="ids" value="{{ email.uid if thread else email.gm_thrid }}" {% if thread %}checked{% endif %}>
            </li>

            <li class="email-star{% if email.starred %} email-starred{% endif %}"></li>

            <li class="email-info email-pics">
                {{ gravatars(email.from_) }}
            </li>

            <li class="email-info email-from" title="{{ email.str_from(full=True)|e }}">
                {{ email.str_from() }}
            </li>

            {% if not thread and email.labels %}
            <li class="email-labels">
            {% for l in email.full_labels if not l.hidden and l != label%}
                <a href="{{ l.url }}">{{ l.human_name }}</a>
            {% endfor %}
            </li>
            {% endif %}

            {% with subj, text = email.text_line %}
            <li class="email-info email-subject">
            {% if thread %}
                {{ text or '(no text)' }}
            {% else %}
                {% set count = counts[email.gm_thrid] %}
                {% if count > 1 %}<span class="email-count">{{ count }}</span>{% endif %}
                <b>{{ subj }}</b>{% if text %} {{ text|e }}{% endif %}
            {% endif %}
            </li>
            {% endwith %}

            <li class="email-info email-date" title="{{ email.date|format_dt }}">
                {{ email.date|humanize_dt }}
            </li>
        </ul>

        {% if thread %}
        <ul class="email-head">
            <li class="email-star{% if email.starred %} email-starred{% endif %}"></li>
            <li>
                <a href="{{ url_for('raw', email=email.uid) }}" title="Raw message" target="_blank">[r]</a>
                {% set url = '%s?email=%s' % (url_for('emails'), email.from_|get_addr) %}
                <a href="{{ url }}" title="Filter by <{{ email.from_|get_addr }}>" class="email-filter">[f]</a>
                {% set url = '%s?subj=%s' % (url_for('emails'), email.clean_subject) %}
                <a href="{{ url }}" title="Filter by subject" class="email-filter">[s]</a>
            </li>
            <li class="email-info email-pics">
                {{ gravatars(email.from_) }}
            </li>
            <li class="email-info email-from" title="{{ email.str_from(full=True)|e }}">
                {{ email.str_from() }}
            </li>
            <li class="email-info email-subject">
                {{ email.human_subject(strip=False) }}
            </li>
            <li class="email-info email-date">
                {{ email.date|format_dt }}
            </li>
        </ul>
        <div class="email-body">
            {{ email.human_html('email-quote') }}
            {% if email.attachments %}
            <div class="email-attachments">
                <h3>Attachments:</h3>
                <ul>
                {% for item in email.attachments %}
                    <li><a href="/attachments/{{ item }}">{{ item.split('/')[-1] }}</a></li>
                {% endfor %}
                </ul>
            </div>
        </div>
        {% endif %}
        {% endif %}
    </li>
{% endfor %}
</ul>

{% if emails_count and emails_count > max_count %}
<div class="email-show" data-count={{ max_count }}>
    <a class="show-all">Show all</a>
    {% if (emails_count / max_count) > 2 %}
    <a class="show-next">Show next {{ max_count }}</a>
    {% endif %}
</div>
{% endif %}
{% endmacro %}

<div class="panel-head">
    {% if labels %}
    <div class="inputs">
    <button name="search" class="search" title="Search"></button>
    <select class="labels">
        <option value="">
        {% for label in labels %}
        <option value="{{ label.url }}" data-id="{{ label.id }}">
            {{ label.human_name }} <b>{{ label.unread }}</b>/{{ label.exists }}
        </option>
        {% endfor %}
    </select>
    <form class="search-query" method="get">
        <input name="q">
        <button type="submit" class="search-go" title="Go!">Go!</button>
    </form>
    <button name="refresh" class="refresh" title="Refresh"></button>
    </div>
    <button name="mark" value="archived">Archive</button>
    <button name="mark" value="deleted">Delete</button>
    <button name="mark" value="inboxed">Move to Inbox</button>
    {#
    <button name="mark" value="starred">Add star</button>
    <button name="mark" value="unstarred">Remove star</button>
    #}
    <button name="mark" value="read">Read</button>
    <button name="mark" value="unread">Unread</button>
    {% endif %}
</div>

<div class="panel-body">
    {% block content %}
    {% if emails %}
    <div class="label">
        {{ render(emails, counts=counts) }}
    </div>
    {% endif %}
    {% endblock %}
</div>
