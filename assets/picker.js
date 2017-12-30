import Vue from 'vue';
import { contains } from './utils.js';
import tpl from './picker.html';

Vue.component('picker', {
  template: tpl,
  props: {
    opts: { type: Array, required: true },
    value: { type: String, required: true },
    title: { type: String, default: '' },
    filterOff: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
    perPage: { type: Number, default: 15 },
    fnUpdate: { type: Function, default: val => val },
    fnFilter: { type: Function, default: contains },
    fnApply: { type: Function },
    fnCancel: { type: Function }
  },
  data: function() {
    return {
      filter: this.value,
      selected: this.value,
      active: false
    };
  },
  mounted: function() {
    window.addEventListener('focus', this.focus, true);
    window.addEventListener('click', this.focus, true);
  },
  destroyed: function() {
    window.removeEventListener('focus', this.focus, true);
    window.removeEventListener('click', this.focus, true);
  },
  computed: {
    filtered: function() {
      if (this.filter == this.value) {
        return this.opts;
      }

      return this.opts.filter(val => this.fnFilter(val, this.filter));
    }
  },
  methods: {
    focus: function(e) {
      if (e.target == window) {
        return;
      }
      if (this.$el.contains(e.target)) {
        this.active || this.activate();
        return;
      }
      if (this.active) {
        this.cancel();
        this.$refs.input.blur();
      }
    },
    set: function(val) {
      val = val === undefined ? this.selected : val;
      this.active = this.fnApply ? true : false;
      if (this.active) {
        this.$refs.input.focus();
      }
      if (!val) {
        return;
      }
      this.fnUpdate(val);
      if (this.value) {
        this.selected = val;
        this.filter = val;
      } else {
        this.filter = this.value;
      }
    },
    cancel: function() {
      this.fnCancel && this.fnCancel();
      this.set(this.value);
      this.active = false;
    },
    apply: function() {
      this.fnApply ? this.fnApply() : this.set();
    },
    activate: function() {
      if (this.disabled) {
        return;
      }
      this.$refs.input.focus();
      this.active = true;
      this.$nextTick(() => {
        let element = this.selectedOpt();
        if (!element) {
          return;
        }
        // make selected option visible if scroll exists
        let opts = this.$refs.opts;
        if (opts.scrollHeight == opts.clientHeight) {
          return;
        }
        for (let i = 0; i < 3; i++) {
          if (element.previousSibling) {
            element = element.previousSibling;
          }
        }
        opts.scrollTop = element.offsetTop;
      });
    },
    selectedOpt: function() {
      return (
        this.$el.querySelector('.picker__opts__item--active') ||
        this.$el.querySelector('.picker__opts__item')
      );
    },
    select: function(key, count = 1) {
      if (!this.selectedOpt()) {
        return;
      }
      let val, idx;
      idx = this.filtered.indexOf(this.selectedOpt().dataset.value);
      for (let i = 0; i < count; i++) {
        idx = key == 'up' ? idx - 1 : idx + 1;
        if (idx < 0) {
          val = this.filtered[0];
        } else if (idx > this.filtered.length - 1) {
          val = this.filtered[this.filtered.length - 1];
        } else {
          val = this.filtered[idx];
        }
      }
      this.selected = val;
      this.activate();
    }
  }
});
