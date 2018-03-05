import Vue from 'vue';
import { call } from './utils.js';
import { Slider } from './slider.js';
import tpl from './editor.html';

Vue.component('editor', {
  template: tpl,
  props: {
    msg: { type: Object, required: true },
    query: { type: Function, required: true },
    refresh: { type: Function, required: true },
    cancel: { type: Function, required: true }
  },
  data: function() {
    return {
      edit: true,
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
    if (data && data.time > this.msg.time) {
      Object.assign(this, data);
    }
  },
  methods: {
    autosave: function() {
      let data = this.values();
      data.time = new Date().getTime();
      window.localStorage.setItem(this.msg.draft_id, JSON.stringify(data));
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
      data.append('uid', this.msg.uid);
      for (let i in this.values()) {
        data.append(i, this.values[i]);
      }
      for (let file of Array.from(this.$refs.upload.files || [])) {
        data.append('files', file, file.name);
      }
      return call('post', '/editor', data, {}).then(res => {
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
      this.edit = false;
      call('post', '/markdown', { txt: this.txt }).then(
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
        call('get', url_send).then(res => this.query(res.query));
      } else {
        this.countdown = null;
      }
    }
  }
});
