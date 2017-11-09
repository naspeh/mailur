import Vue from 'vue';
import { trancate } from './utils.js';
import tpl from './tags.html';
import './tags.css';

Vue.component('Tags', {
  template: tpl,
  props: {
    trancate: { type: Boolean, default: false },
    raw: { type: Array, required: true }
  },
  computed: {
    display: function() {
      let all = window.app.tags;
      let tags = [];
      for (let id of this.raw) {
        let val = {
          title: all[id] ? all[id] : id,
          id: id
        };
        val['name'] = this.trancate ? trancate(val.title) : val.title;
        tags.push(val);
      }
      return tags;
    },
    app: () => window.app
  }
});
