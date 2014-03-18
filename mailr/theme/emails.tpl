{% macro gravatars(addrs, size=16) %}
    {% for addr in addrs %}
        <img src="{{ addr|get_gravatar(size) }}"
            height="{{ size }}" width="{{ size }}"
            alt="{{ addr|e }}" title="{{ addr|e }}"/>
    {% endfor %}
{% endmacro %}

{% macro render(emails, thread=False, show=False) %}
<ul class="emails">
{% for email in emails %}
    <li class="email
            {% if email.unread %} email-unread{% endif %}
            {% if show %} email-showed{% endif %}
        "
        data-id="{{ email.uid }}"
        data-raw="{{ url_for('raw', email=email.uid) }}"
        data-thread="{{ url_for('gm_thread', id=email.gm_thrid) }}"
    >
        <ul class="email-line">
            <li class="email-pick">
                <input type="checkbox" name="ids" value="{{ email.uid }}" {% if thread %}checked{% endif %}>
            </li>

            <li class="email-star{% if email.starred %} email-starred{% endif %}"></li>

            <li class="email-info email-pics">
                {{ gravatars(email.from_) }}
            </li>

            <li class="email-from" title="{{ email.from_|join(', ')|e }}">
                <a href="/emails/?email={{ email.from_[0]|get_addr }}">
                    {{ email.from_|map('get_addr')|join(', ') }}
                </a>
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

            <li class="email-info email-pics">
                {{ gravatars(email.from_) }}
            </li>

            <li class="email-info email-from" title="{{ email.from_|join(', ')|e }}">
                {{ email.from_|map('get_addr')|join(', ') }}
            </li>

            <li class="email-info email-subject">
                {{ email.human_subject(strip=False) }}
            </li>

            <li class="email-info email-date">{{ email.date|format_dt }}</li>
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
{% endmacro %}

{% if emails or groups %}
<form name="emails-form" class="emails-form" method="POST">
    {#<button name="sync_all">Sync all</button>#}
    <button name="sync">Sync</button>
    <button name="mark" value="archived">Archive</button>
    <button name="mark" value="deleted">Delete</button>
    <button name="copy_to_inbox">Move to Inbox</button>
    <button name="mark" value="starred">Add star</button>
    <button name="mark" value="unstarred">Remove star</button>
    <button name="mark" value="read">Read</button>
    <button name="mark" value="unread">Unread</button>
    {% block content %}
    <div class="label">
        {{ render(emails) }}
    </div>
    {% endblock %}
</form>
{% endif %}
