import Vue from 'vue';
import { call } from './utils.js';
import tpl from './msgs.html';

export default function(params) {
  let data = { propsData: params };
  return params.thread ? new Thread(data) : new Msgs(data);
}

let Base = {
  template: tpl,
  props: {
    cls: { type: String, required: true },
    query: { type: String, required: true },
    uids: { type: Array, required: true },
    msgs: { type: Object, required: true },
    msgs_info: { type: String, required: true },
    open: { type: Function, required: true },
    search: { type: Function, required: true },
    pics: { type: Function, required: true }
  },
  created: function() {
    this.$mount(`.${this.cls}`);
    this.pics(this.msgs);
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
    setMsgs: function(msgs) {
      this.msgs = Object.assign({}, this.msgs, msgs);
      this.pics(msgs);
    },
    newQuery: function() {
      this.clean();
      this.open(this.query);
    },
    archive: function() {
      return this.editFlags({ old: ['#inbox'] });
    },
    del: function() {
      return this.editFlags({ new: ['#trash'] });
    }
  }
};

let Msgs = Vue.extend({
  mixins: [Base],
  props: {
    threads: { type: Boolean, required: true }
  },
  data: function() {
    return {
      name: 'msgs',
      perPage: 200,
      picked: [],
      detailed: null
    };
  },
  computed: {
    flags: function() {
      if (!this.uids.length) {
        return [];
      }
      let flags = [];
      for (let i of this.picked) {
        flags.push.apply(flags, this.msgs[i].flags);
      }
      return [...new Set(flags)];
    }
  },
  methods: {
    clean: function() {
      this.uids = [];
      this.msgs = {};
      this.picked = [];
    },
    refresh: function() {
      let uids = this.loaded;
      this.search(this.query).then(res => {
        this.uids = res.uids;
        this.setMsgs(res.msgs);
        this.call('post', this.msgs_info, { uids: uids }).then(res =>
          this.setMsgs(res)
        );
      });
    },
    pick: function(uid) {
      let idx = this.picked.indexOf(uid);
      if (idx == -1) {
        this.picked.push(uid);
      } else {
        this.picked.splice(idx, 1);
      }
    },
    pickAll: function() {
      this.picked = this.loaded;
    },
    pickNone: function() {
      this.picked = [];
    },
    link: function() {
      this.call('post', '/thrs/link', { uids: this.picked }).then(this.refresh);
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
      return this.call('post', this.msgs_info, { uids: uids }).then(res =>
        this.setMsgs(res)
      );
    },
    details: function(uid) {
      if (this.detailed == uid) {
        this.detailed = null;
      } else {
        this.detailed = uid;
      }
    },
    editFlags: function(opts, picked = null) {
      opts = Object.assign({ uids: picked || this.picked }, opts);
      call('post', '/msgs/flag', opts).then(res => {
        if (!res.errors) {
          this.refresh();
        }
      });
    }
  }
});

let Thread = Vue.extend({
  mixins: [Base],
  props: {
    thread: { type: Object, required: true },
    same_subject: { type: Array, required: true }
  },
  data: function() {
    return {
      name: 'thread',
      preload: 4,
      detailed: []
    };
  },
  methods: {
    clean: function() {
      this.uids = [];
      this.msgs = {};
      this.thread = null;
    },
    loadAll: function() {
      return this.call('post', this.msgs_info, {
        uids: this.hidden,
        hide_flags: this.thread.flags
      }).then(msgs => this.setMsgs(msgs));
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
      let preload = this.hidden.length > 0 ? this.preload : null;
      opts = Object.assign({ uids: picked || this.uids }, opts);
      call('post', '/msgs/flag', opts).then(res => {
        if (!res.errors) {
          this.search(this.query, preload).then(res => {
            this.uids = res.uids;
            this.thread = res.thread;
            this.setMsgs(res.msgs);
          });
        }
      });
    }
  }
});
