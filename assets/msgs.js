import Vue from 'vue';
import { call } from './utils.js';
import tpl from './msgs.html';

export default function(params) {
  let data = { propsData: params };
  return params.tags ? new Thread(data) : new Msgs(data);
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
    refresh: function(hide_tags) {
      let data = { uids: this.loaded, hide_tags: hide_tags };
      this.search(this.query).then(res => {
        this.set(res);
        call('post', this.msgs_info, data).then(this.setMsgs);
      });
    },
    setMsgs: function(msgs) {
      this.msgs = Object.assign({}, this.msgs, msgs);
      this.pics(msgs);
    },
    newQuery: function() {
      this.clean();
      this.open(this.query);
    },
    archive: function() {
      return this.editTags({ old: ['#inbox'] });
    },
    del: function() {
      return this.editTags({ new: ['#trash'] });
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
    tags: function() {
      if (!this.uids.length) {
        return [];
      }
      let tags = [];
      for (let i of this.picked) {
        tags.push.apply(tags, this.msgs[i].tags);
      }
      return [...new Set(tags)];
    }
  },
  methods: {
    clean: function() {
      this.uids = [];
      this.msgs = {};
      this.picked = [];
    },
    set: function(res) {
      this.uids = res.uids;
      this.setMsgs(res.msgs);
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
      call('post', '/thrs/link', { uids: this.picked }).then(this.refresh);
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
      return call('post', this.msgs_info, { uids: uids }).then(this.setMsgs);
    },
    details: function(uid) {
      if (this.detailed == uid) {
        this.detailed = null;
      } else {
        this.detailed = uid;
      }
    },
    editTags: function(opts, picked = null) {
      picked = picked || this.picked;

      let uids;
      if (!opts['new'] && opts.old.indexOf('\\Seen') != -1) {
        uids = picked;
      } else if (!opts.old && opts['new'].indexOf('\\Flagged') != -1) {
        uids = picked;
      } else {
        uids = [];
        for (let i of picked) {
          uids.push.apply(uids, this.msgs[i].uids);
        }
      }

      opts = Object.assign({ uids: uids }, opts);
      return call('post', '/msgs/flag', opts).then(res => {
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
    tags: { type: Array, required: true },
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
      this.tags = [];
    },
    set: function(res) {
      this.uids = res.uids;
      this.tags = res.tags;
      this.setMsgs(res.msgs);
    },
    loadAll: function() {
      return call('post', this.msgs_info, {
        uids: this.hidden,
        hide_tags: this.tags
      }).then(this.setMsgs);
    },
    details: function(uid) {
      let idx = this.detailed.indexOf(uid);
      if (idx == -1) {
        this.detailed.push(uid);
      } else {
        this.detailed.splice(idx, 1);
      }
    },
    editTags: function(opts, picked = null) {
      let preload = this.hidden.length > 0 ? this.preload : null;
      opts = Object.assign({ uids: picked || this.uids }, opts);
      return call('post', '/msgs/flag', opts).then(res => {
        if (!res.errors) {
          this.search(this.query, preload).then(() => this.refresh(this.tags));
        }
      });
    }
  }
});
