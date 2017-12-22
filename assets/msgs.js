import Vue from 'vue';
import './msg-line.js';
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
      picSize: 20,
      query: this._query,
      uids: [],
      pages: [],
      url: null,
      threads: null,
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
        this.picked = [];
        this.addrs = [];
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
        this.threads = res.threads;
        if (res.hidden === undefined) {
          this.setMsgs(res.msgs, res.uids.slice(0, this.perPage));
        } else {
          this.setMsgs(res.msgs, res.uids);
        }
        this.uids = res.uids;
      });
    },
    pics: function(msgs) {
      let hashes = [];
      for (let m in msgs) {
        for (let f of msgs[m].from_list) {
          if (
            f.hash &&
            hashes.indexOf(f.hash) == -1 &&
            this.addrs.indexOf(f.hash) == -1
          ) {
            hashes.push(f.hash);
          }
        }
      }
      if (hashes.length == 0) {
        return;
      }
      this.addrs = this.addrs.concat(hashes);
      while (hashes.length > 0) {
        let sheet = document.createElement('link');
        let few = encodeURIComponent(hashes.splice(0, 50));
        sheet.href = `/avatars.css?size=${this.picSize}&hashes=${few}`;
        sheet.rel = 'stylesheet';
        document.body.appendChild(sheet);
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
    },
    open: function(msg) {
      if (this.threads) {
        this.fetch(msg.query_thread);
      } else {
        this.details(msg.uid);
      }
    },
    canOpenInSplit: function() {
      return this.split && !window.app.$refs.main.threads;
    },
    openInSplit: function(query) {
      if (!query) {
        query = window.app.$refs.main.query;
      }
      return window.app.openInSplit(query);
    }
  }
});
