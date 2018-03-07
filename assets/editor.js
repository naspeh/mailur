import Vue from 'vue';
import { Slider } from './slider.js';
import tpl from './editor.html';

Vue.component('editor', {
  template: tpl,
  props: {
    msg: { type: Object, required: true },
    call: { type: Function, required: true },
    query: { type: Function, required: true },
    query_thread: { type: String, required: true },
    refresh: { type: Function, required: true }
  },
  data: function() {
    return {
      editing: true,
      countdown: null,
      html: '',
      from: this.msg.from,
      to: this.msg.to,
      subject: this.msg.subject,
      txt: this.msg.txt
    };
  },
  created: function() {
    let data = window.localStorage.getItem(this.msg.draft_id);
    data = (data && JSON.parse(data)) || {};
    if (data && data.time > this.msg.time * 1000) {
      Object.assign(this, data);
    }
  },
  methods: {
    autosave: function() {
      let data = this.values();
      data.time = new Date().getTime();
      window.localStorage.setItem(this.msg.draft_id, JSON.stringify(data));
    },
    cancel: function() {
      window.localStorage.removeItem(this.msg.draft_id);
      this.query(this.query_thread);
    },
    values: function() {
      let values = {};
      for (let i of ['from', 'to', 'subject', 'txt']) {
        values[i] = this[i];
      }
      return values;
    },
    save: function(refresh = true) {
      let data = new FormData();
      let values = this.values();
      for (let i in values) {
        data.append(i, values[i]);
      }
      for (let file of Array.from(this.$refs.upload.files || [])) {
        data.append('files', file, file.name);
      }
      data.append('uid', this.msg.uid);
      return this.call('post', '/editor', data, {}).then(res => {
        refresh && this.refresh();
        return res;
      });
    },
    slide: function(e, idx) {
      e.preventDefault();
      new Slider({
        el: '.slider',
        propsData: {
          slides: this.msg.files.filter(i => i.image),
          index: idx
        }
      });
    },
    preview: function() {
      this.editing = false;
      this.call('post', '/markdown', { txt: this.txt }).then(
        res => (this.html = res)
      );
    },
    send: function() {
      this.preview();
      this.countdown = 5;
      this.save(false).then(res => this.sending(res.url_send));
    },
    sending: function(url_send) {
      if (this.countdown > 0) {
        this.countdown = this.countdown - 1;
        setTimeout(() => this.sending(url_send), 1000);
      } else if (this.countdown == 0) {
        this.call('get', url_send).then(res => this.query(res.query));
      } else {
        this.countdown = null;
      }
    },
    edit: function() {
      this.editing = true;
      if (this.countdown) {
        this.countdown = null;
        this.refresh();
      }
    }
  }
});
