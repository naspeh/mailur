<!DOCTYPE HTML>
<html lang="en">
<head>
    <title>Mail Client</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="/theme/all.css">
</head>
<body>
<div class="panel-one">
    <select class="labels">
    {% for label in labels %}
        <option value="#{{ url_for('label', id=label.id) }}">
            {{ label.human_name }} <b>{{ label.unread }}</b>/{{ label.exists }}
        </option>
    {% endfor %}
    </select>
    <div class="panel-body"
</div>
<script src="//code.jquery.com/jquery.js"></script>
<script>
$(window).bind('hashchange', function() {
    var url = location.hash.slice(1);
    $('select.labels [value="#' + url + '"]').attr('selected', true);
    $.get(url, function(content) {
        $('.label-active').removeClass('label-active');
        $('.labels a[href="#' + url + '"]').addClass('label-active');

        $('.panel-one .panel-body').html(content);

        $('.email-star').bind('click', function() {
            var $this = $(this);
            do_star($($this.parents('.email')), $this.hasClass('email-starred'));
        });

        $('form[name="emails-form"] input[type="submit"]').click(function() {
            var $this = $(this);
            var items = $this.parents('form')
                .find('input[name="ids"]:checked').parents('.email');
            do_star(items, $this.attr('name') == 'rm-star');
            return false;
        });
    });
    function do_star(items, unset) {
        var ids = [];
        items.each(function() {
            ids.push($(this).data('id'));
        });
        var data = {ids: ids, unset: unset && 1 || ''};
        var stars = items.find('.email-star')
        stars.toggleClass('email-starred');
        $.post('/change-label/', data)
            .fail(function() {
                stars.toggleClass('email-starred');
            });
    }
});
$('select.labels')
    .bind('change', function() {
        window.location.hash = $(this).val();
    });
if (window.location.hash) {
    $('select.labels [value="' + window.location.hash + '"]').attr('selected', true);
    $(window).trigger('hashchange');
} else {
    $('select.labels').trigger('change');
}
</script>
</body>
</html>
