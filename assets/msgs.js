import Vue from 'vue';
import { send } from './utils.js';
import tpl from './msgs.html';
import './msgs.css';

Vue.component('Msgs', {
  template: tpl,
  props: {
    _query: { type: String, default: null },
    side: { type: Boolean, default: false }
  },
  data: function() {
    return {
      query: this._query,
      uids: [],
      perPage: 200,
      pages: [],
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
    },
    threads: function() {
      return this.query.indexOf(':threads ') == 0;
    }
  },
  methods: {
    send: send,
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
      if (query && !this.side) {
        window.app.query = query;
      }

      this.uids = [];
      this.setMsgs();
      return this.send('/search', {
        q: this.query,
        preload: this.perPage
      }).then(res => {
        this.url = res.msgs_url;
        this.setMsgs(res.msgs, res.uids.slice(0, this.perPage));
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
        sheet.href = '/api/avatars.css?size=18&hashes=' + few;
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
      this.send('/thrs/link', { uids: this.picked }).then(() => this.fetch());
    },
    canLoadMore: function() {
      return this.length < this.uids.length;
    },
    loadMore: function() {
      let uids = this.uids.slice(this.length, this.length + this.perPage);
      return this.send(this.url, { uids: uids }).then(res =>
        this.setMsgs(res, uids)
      );
    },
    page: function(uids) {
      let msgs = [];
      for (const uid of uids) {
        // if (!this.msgs[uid]) console.error(`No message for uid=${uid}`);
        msgs.push(this.msgs[uid]);
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
    searchHeader: function(name, value) {
      value = JSON.stringify(value);
      return this.fetch(`:threads header ${name} ${value}`);
    },
    searchTag: function(tag) {
      let q;
      if (tag[0] == '\\') {
        q = tag.slice(1);
      } else {
        tag = JSON.stringify(tag);
        q = `keyword ${tag}`;
      }
      q = ':threads ' + q;
      return this.fetch(q);
    },
    searchAddr: function(addr) {
      this.fetch(`:threads from ${addr}`);
    },
    thread: function(uid, side) {
      let q = `inthread refs uid ${uid}`;
      if (side) {
        return this.openInSide(q);
      }
      return this.fetch(q);
    },
    canOpenInSide: function() {
      return this.side && !window.app.$refs.main.threads;
    },
    openInSide: function(query) {
      if (!query) {
        query = window.app.$refs.main.query;
      }
      return window.app.openInSide(query);
    },
    hasSide: function() {
      return !this.side && window.app.side;
    }
  }
});
