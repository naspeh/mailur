<ul class="messages">
{% for email in emails %}
    <li>{{ email.subject }}</li>
{% endfor %}
</ul>
