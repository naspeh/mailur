import Vue from 'vue';
import { call } from './utils.js';
import tpl from './msgs.html';

Vue.component('msgs', {
  template: tpl,
  props: {
    _query: { type: String, default: null },
    split: { type: Boolean, default: false }
  },
  data: function() {
    return {
      perPage: 200,
      query: this._query,
      uids: [],
      pages: [],
      url: null,
      threads: false,
      picked: [],
      detailed: null
    };
  },
  created: function() {
    this.setMsgs();
    if (this.query) {
      this.fetch(this.query);
    }
  },
  computed: {
    length: function() {
      return this.pages.length
        ? Object.getOwnPropertyNames(this.msgs).length
        : 0;
    }
  },
  methods: {
    call: call,
    setMsgs: function(msgs, uids) {
      if (!msgs) {
        this.msgs = {};
        this.pages = [];
        //this.picked = [];
      } else {
        Object.assign(this.msgs, msgs);
        this.pages.push(uids);
        this.pics(msgs);
      }
    },
    fetch: function(query) {
      if (query) {
        this.query = query;
      }
      if (query && !this.split) {
        window.app.query = query;
      }

      this.uids = [];
      this.setMsgs();
      return this.call('post', '/search', {
        q: this.query,
        preload: this.perPage
      }).then(res => {
        this.url = res.msgs_info;
        this.threads = res.threads || false;
        if (res.hidden === undefined) {
          this.setMsgs(res.msgs, res.uids.slice(0, this.perPage));
        } else {
          this.setMsgs(res.msgs, res.uids);
        }
        this.uids = res.uids;
      });
    },
    pics: msgs => window.app.pics(msgs),
    pick: function(uid) {
      let idx = this.picked.indexOf(uid);
      if (idx == -1) {
        this.picked.push(uid);
      } else {
        this.picked.splice(idx, 1);
      }
    },
    pickAll: function() {
      this.picked = Object.keys(this.msgs);
    },
    pickNone: function() {
      this.picked = [];
    },
    link: function() {
      this.call('post', '/thrs/link', { uids: this.picked }).then(() =>
        this.fetch()
      );
    },
    canLoadMore: function() {
      return this.length < this.uids.length;
    },
    loadMore: function() {
      let uids = [];
      for (let uid of this.uids) {
        if (!this.msgs[uid]) {
          uids.push(uid);
          if (uids.length == this.perPage) {
            break;
          }
        }
      }
      return this.call('post', this.url, { uids: uids }).then(res =>
        this.setMsgs(res, uids)
      );
    },
    page: function(uids) {
      let msgs = [];
      for (const uid of uids) {
        // if (!this.msgs[uid]) console.error(`No message for uid=${uid}`);
        if (this.msgs[uid]) {
          msgs.push(this.msgs[uid]);
        }
      }
      return msgs;
    },
    details: function(uid) {
      if (this.detailed == uid) {
        this.detailed = null;
      } else {
        this.detailed = uid;
      }
    }
  }
});
