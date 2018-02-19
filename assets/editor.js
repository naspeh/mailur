import Vue from 'vue';
import tpl from './editor.html';

Vue.component('editor', {
  template: tpl,
  props: {
    msg: { type: Object, required: true }
  },
  methods: {}
});
