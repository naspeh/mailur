import Vue from 'vue';
import { call } from './utils.js';
import tpl from './thread.html';

Vue.component('thread', {
  template: tpl,
  props: {
    query: { type: String, default: null },
    split: { type: Boolean, default: false }
  },
  data: function() {
    return {
      uids: [],
      hidden: [],
      msgs: {},
      url: null,
      detailed: []
    };
  },
  created: function() {
    if (this.query) {
      this.fetch(this.query);
    }
  },
  computed: {
    length: function() {
      return Object.getOwnPropertyNames(this.msgs).length;
    }
  },
  methods: {
    call: call,
    pics: msgs => window.app.pics(msgs),
    fetch: function(query, preload = 4) {
      if (query && !this.split) {
        window.app.query = query;
      }

      this.uids = [];
      this.msgs = {};
      return this.call('post', '/search', {
        q: this.query,
        preload: preload
      }).then(res => {
        this.url = res.msgs_info;
        this.uids = res.uids;
        this.msgs = res.msgs;
        this.hidden = res.hidden;
        this.same_subject = res.same_subject;
        this.pics(this.msgs);
      });
    },
    loadAll: function() {
      let uids = [];
      for (let uid of this.uids) {
        if (!this.msgs[uid]) {
          uids.push(uid);
        }
      }
      return this.call('post', this.url, { uids: uids }).then(msgs => {
        this.msgs = Object.assign({}, this.msgs, msgs);
        this.hidden = [];
        this.pics(msgs);
      });
    },
    details: function(uid) {
      let idx = this.detailed.indexOf(uid);
      if (idx == -1) {
        this.detailed.push(uid);
      } else {
        this.detailed.splice(idx, 1);
      }
    }
  }
});
