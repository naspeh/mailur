import Vue from "vue";

var app = new Vue({
  el: "#app",
  data: {
    uids: [],
    state: {},
    query: decodeURIComponent(location.hash.slice(1)) || "all",
    show_threads: false,
    show_bodies: false,
    per_page: 100
  },
  computed: {
    uidsLoaded: function() {
      var uids = [];
      for (var uid of this.uids) {
        if (this.state[uid]) {
          uids.push(uid);
        }
      }
      return uids;
    }
  },
  methods: {
    get: function(query) {
      if (query) {
        this.query = query;
      }
      window.location.hash = this.query;
      this.send("", {
        q: this.query,
        preload: this.per_page
      }).then(res => {
        this.msgs = res.msgs;

        this.ids(res.uids.slice(0, this.per_page));
        this.infos(res.msgs);
        if (res.uids.length > this.per_page) {
          setTimeout(() => this.ids(res.uids), 0);
        }
      });
    },
    canLoadMore() {
      return (
        Object.getOwnPropertyNames(this.msgs || {}).length < this.uids.length
      );
    },
    loadMore: function() {
      var start = Object.getOwnPropertyNames(this.msgs).length,
        uids = this.uids.slice(start, start + this.per_page);
      this.send("/info", { uids: uids }).then(this.infos);
    },
    ids: function(uids) {
      this.uids = uids;
      var state = this.uids.reduce((acc, cur) => {
        acc[cur] = this.msgs && this.msgs[cur] ? 1 : 0;
        return acc;
      }, {});
      this.state = state;
    },
    infos: function(msgs) {
      this.msgs = Object.assign(this.msgs, msgs);
      var state = {};
      for (var msg in msgs) {
        state[msg] = 1;
      }
      this.state = Object.assign(this.state, state);
    },
    url: function(url, params) {
      url = (this.show_threads ? "/api/threads" : "/api/msgs") + url;
      return (params && url + encodeURIComponent(this.query)) || url;
    },
    send: function(url, params) {
      url = this.url(url);
      return fetch(url, {
        method: "post",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params)
      }).then(response => response.json());
    },
    origin_url: function(uid) {
      return "/api/origin/" + this.msgs[uid].uid;
    },
    parsed_url: function(uid) {
      return "/api/parsed/" + uid;
    },
    search: function(query) {
      query = (app.show_threads && query) || "inthread refs " + query;
      return app.get(query);
    },
    search_header: function(name, value) {
      return app.search("header " + name + ' "' + value + '"');
    }
  }
});
app.msgs = {};
