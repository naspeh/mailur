import Vue from 'vue';
import { send } from './utils.js';
import tpl from './msgs.html';
import './msgs.css';

Vue.component('Msgs', {
  template: tpl,
  data: function() {
    return {
      query: null,
      threads: false,
      uids: [],
      perPage: 200,
      pages: [],
      picked: []
    };
  },
  created: function() {
    this.setMsgs();
  },
  computed: {
    url: function() {
      return this.threads ? '/thrs' : '/msgs';
    },
    length: function() {
      return this.pages.length
        ? Object.getOwnPropertyNames(this.msgs).length
        : 0;
    },
    app: () => window.app
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
    fetch: function() {
      this.uids = [];
      this.setMsgs();
      this.query = this.$parent.query;
      this.threads = this.$parent.threads;
      return this.send(this.url, {
        q: this.query,
        preload: this.perPage
      }).then(res => {
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
    pickAll: function(e) {
      if (e.target.checked) {
        this.picked = Object.keys(this.msgs);
      } else {
        this.picked = [];
      }
    },
    link: function() {
      this.send('/thrs/link', { uids: this.picked }).then(() => this.fetch());
    },
    canLoadMore: function() {
      return this.length < this.uids.length;
    },
    loadMore: function() {
      let uids = this.uids.slice(this.length, this.length + this.perPage);
      return this.send(this.url + '/info', { uids: uids }).then(res =>
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
    }
  }
});
