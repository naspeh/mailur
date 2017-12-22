import Vue from 'vue';
import tpl from './picker.html';

Vue.component('picker', {
  template: tpl,
  props: {
    value: { type: String, required: true },
    options: { type: Array, required: true },
    perPage: { type: Number, default: 15 },
    disabled: { type: Boolean, default: false }
  },
  data: function() {
    return {
      filter: this.value,
      filterOff: this.options.length <= this.perPage,
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
        return this.options;
      }

      let opts = [];
      for (let opt of this.options) {
        if (opt.toLowerCase().indexOf(this.filter.toLowerCase()) != -1) {
          opts.push(opt);
        }
      }
      return opts;
    }
  },
  methods: {
    focus: function(e) {
      if (e.target == window) {
        return;
      }
      if (
        this.$el.contains(e.target) &&
        e.target.className.indexOf('picker') != -1
      ) {
        this.activate();
        return;
      }
      if (this.active) {
        this.set();
      }
    },
    set: function(val, active = false) {
      val = val || this.selected;
      this.$emit('update:value', val);
      this.selected = val;
      this.filter = val;
      if (active) {
        this.activate();
        this.$el.querySelector('.picker__input').focus();
      } else if (this.active) {
        this.active = false;
      }
    },
    activate: function() {
      if (this.disabled) {
        return;
      }
      this.active = true;
      this.$nextTick(() => {
        let element = this.selectedOpt();
        if (!element) {
          return;
        }
        for (let i = 0; i < 3; i++) {
          if (element.previousSibling) {
            element = element.previousSibling;
          }
        }
        element.scrollIntoView();
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
          val = this.filtered[this.filtered.length - 1];
        } else if (idx > this.filtered.length - 1) {
          val = this.filtered[0];
        } else {
          val = this.filtered[idx];
        }
      }
      this.selected = val;
      this.activate();
    }
  }
});
