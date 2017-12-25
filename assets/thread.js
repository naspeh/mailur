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
      uids: null,
      msgs: null,
      thread: null,
      url: null,
      detailed: [],
      same_subject: null
    };
  },
  created: function() {
    if (this.query) {
      this.fetch(this.query);
    }
  },
  computed: {
    hidden: function() {
      let uids = [];
      for (let uid of this.uids) {
        if (!this.msgs[uid]) {
          uids.push(uid)
        }
      }
      return uids;
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
        this.thread = res.thread;
        this.uids = res.uids;
        this.msgs = res.msgs;
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
      return this.call('post', this.url, {
        uids: uids,
        hide_flags: this.thread.flags
      }).then(msgs => {
        this.msgs = Object.assign({}, this.msgs, msgs);
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
    },
    edit: function(opts) {
      call('post', '/msgs/flag', Object.assign({ uids: this.uids}, opts))
        .then(() => call('post', '/thrs/info', { uids: [this.thread.uid] }))
        .then(res => (this.thread = res[Object.keys(res)[0]]));
    }
  }
});
