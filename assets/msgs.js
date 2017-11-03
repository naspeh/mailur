import Vue from 'vue';
import tpl from 'html-loader!./msgs.html';

Vue.component('Msgs', {
  template: tpl,
  data: function() {
    return {
      uids: [],
      perPage: 100,
      pages: [],
      url: ''
    };
  },
  created: function() {
    this.setMsgs();
  },
  methods: {
    setMsgs: function(msgs) {
      if (!msgs) {
        this.msgs = {};
        this.pages = [];
      } else {
        Object.assign(this.msgs, msgs);
        this.pages.push(Object.keys(msgs));
      }
      this.length = Object.getOwnPropertyNames(this.msgs).length;
    },
    get: function(url, query) {
      this.url = url;
      this.setMsgs();
      return this.send('', {
        q: query,
        preload: this.perPage
      }).then(res => {
        this.setMsgs(res.msgs);
        this.uids = res.uids;
      });
    },

    send: function(prefix, params) {
      return fetch(this.url + prefix, {
        method: 'post',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
      }).then(response => response.json());
    },

    canLoadMore: function() {
      return this.length < this.uids.length;
    },

    loadMore: function() {
      let uids = this.uids.slice(this.length, this.length + this.perPage);
      return this.send('/info', { uids: uids }).then(res => this.setMsgs(res));
    },

    page: function(uids) {
      let msgs = [];
      for (const uid of uids) {
        let msg = this.msgs[uid];
        msg.parsed_uid = uid;
        msg.origin_url = '/api/origin/' + msg.uid;
        msg.parsed_url = '/api/parsed/' + uid;
        msgs.push(msg);
      }
      return msgs;
    },

    search_header: function(name, value) {
      return this.get('header ' + name + ' "' + value + '"');
    }
  }
});
