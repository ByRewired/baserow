<template>
  <div v-if="impersonating" class="impersonate-warning">
    <i class="impersonate-warning__icon iconoir-group"></i>
    <div class="impersonate-warning__content">
      <div class="impersonate-warning__name">
        {{ $t('impersonateWarning.title', { name }) }}
      </div>
      <a class="impersonate-warning__stop" @click.prevent="stop">{{
        $t('impersonateWarning.stop')
      }}</a>
    </div>
  </div>
</template>

<script>
import { mapGetters } from 'vuex'

export default {
  name: 'SidebarImpersonateWarning',
  computed: {
    ...mapGetters({
      impersonating: 'impersonating/getImpersonating',
      name: 'auth/getName',
    }),
  },
  methods: {
    /**
     * The impersonate endpoint deliberately doesn't overwrite the refresh token
     * cookie, so the admin session is still there. Loading a page without the
     * `__impersonate-user` query parameter therefore restores it.
     */
    stop() {
      window.location.href = this.$router.resolve({
        name: 'admin-users',
      }).href
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../assets/scss/colors';

.impersonate-warning {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background-color: $color-warning-200;
  border-bottom: 1px solid $color-warning-300;
  color: $palette-neutral-1200;

  .sidebar--collapsed & {
    justify-content: center;
  }
}

.impersonate-warning__icon {
  flex: 0 0 auto;
  font-size: 16px;
  color: $color-warning-700;
}

.impersonate-warning__content {
  overflow: hidden;

  .sidebar--collapsed & {
    display: none;
  }
}

.impersonate-warning__name {
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.impersonate-warning__stop {
  font-size: 11px;
  color: $color-warning-800;
  text-decoration: underline;

  &:hover {
    color: $color-warning-900;
  }
}
</style>
