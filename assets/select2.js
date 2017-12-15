import Vue from 'vue';
import tpl from './select2.html';

Vue.component('Select2', {
  template: tpl,
  props: {
    value: { type: String },
    options: { type: Array }
  },
  data: function() {
    return {
      filter: this.value,
      active: false
    };
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
    activate: function() {
      this.active = true;
      this.$nextTick(() => {
        let el = this.$el.querySelector('.select2__select :checked');
        el && el.scrollIntoView();
      });
    },
    deactivate: function() {
      this.active = false;
      this.$el.blur();
    },
    select: function(val = null) {
      val = val || this.$el.querySelector('.select2__select').value;
      this.$emit('update:value', val);
      this.filter = val;
      this.active = false;
    },
    focus: function(label) {
      this.$el.querySelector('.select2__' + label).focus();
    }
  }
});
