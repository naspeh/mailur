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
      preload: 4,
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
    loaded: function() {
      return this.uids.filter(i => this.msgs[i]);
    },
    hidden: function() {
      return this.uids.filter(i => !this.msgs[i]);
    }
  },
  methods: {
    call: call,
    pics: msgs => window.app.pics(msgs),
    fetch: function(query, clean = true, preload = undefined) {
      if (query && !this.split) {
        window.app.query = query;
      }

      if (clean) {
        this.uids = [];
        this.msgs = {};
      }
      return this.call('post', '/search', {
        q: this.query,
        preload: preload === undefined ? this.preload : preload
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
      return this.call('post', this.url, {
        uids: this.hidden,
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
    editFlags: function(opts, picked = null) {
      opts = Object.assign({ uids: picked || this.uids }, opts);
      call('post', '/msgs/flag', opts).then(res => {
        if (!res.errors) {
          this.fetch(
            this.query,
            false,
            this.hidden.length > 0 ? this.preload : null
          );
        }
      });
    }
  }
});
