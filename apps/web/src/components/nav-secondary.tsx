import { valibotResolver } from "@hookform/resolvers/valibot";
import { Settings2 } from "lucide-react";
import { useForm } from "react-hook-form";
import * as v from "valibot";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
} from "@/components/ui/form";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
} from "@/components/ui/sidebar";
import { Textarea } from "@/components/ui/textarea";
import { API_BASE_URL } from "@/config";
import { GetUser, User } from "@/app/api";

const schema = v.object({
  trait: v.string(),
});

type FormSchema = v.InferInput<typeof schema>;

export function NavSecondary({ user }: { user: User }) {
  const form = useForm<FormSchema>({
    resolver: valibotResolver(schema),
    defaultValues: async () => {
      const ret = await fetch(`${API_BASE_URL}/api/users/${user.id}`, {
        method: "GET",
      });
      const { data } = (await ret.json()) as GetUser;
      return { trait: data?.settings?.trait ?? "" };
    },
  });

  async function onSubmit(data: FormSchema) {
    await fetch(`${API_BASE_URL}/api/users/${user.id}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ trait: data.trait }),
    });
  }

  return (
    <SidebarGroup className="mt-auto">
      <SidebarGroupContent>
        <SidebarMenu>
          <SidebarMenuItem>
            <Dialog>
              <DialogTrigger asChild>
                <SidebarMenuButton asChild>
                  <a>
                    <Settings2 />
                    <span>Settings</span>
                  </a>
                </SidebarMenuButton>
              </DialogTrigger>
              <DialogContent className="overflow-hidden p-0 md:max-h-[500px] md:max-w-[700px] lg:max-w-[800px]">
                <DialogTitle className="sr-only">Settings</DialogTitle>
                <DialogDescription className="sr-only">
                  Customize your settings here.
                </DialogDescription>
                <SidebarProvider className="items-start">
                  <Sidebar collapsible="none" className="hidden md:flex">
                    <SidebarContent>
                      <SidebarGroup>
                        <SidebarGroupContent>
                          <SidebarMenu>
                            <SidebarMenuItem>
                              <SidebarMenuButton asChild isActive>
                                <a href="#">
                                  <Settings2 />
                                  <span>Customize wondy</span>
                                </a>
                              </SidebarMenuButton>
                            </SidebarMenuItem>
                          </SidebarMenu>
                        </SidebarGroupContent>
                      </SidebarGroup>
                    </SidebarContent>
                  </Sidebar>
                  <main className="flex h-[480px] flex-1 flex-col overflow-hidden">
                    <header className="flex h-16 shrink-0 items-center gap-2 transition-[width,height] ease-linear group-has-[[data-collapsible=icon]]/sidebar-wrapper:h-12">
                      <div className="flex items-center gap-2 px-4">
                        <Breadcrumb>
                          <BreadcrumbList>
                            <BreadcrumbItem className="hidden md:block">
                              <BreadcrumbLink href="#">Settings</BreadcrumbLink>
                            </BreadcrumbItem>
                            <BreadcrumbSeparator className="hidden md:block" />
                            <BreadcrumbItem>
                              <BreadcrumbPage>Customize wondy</BreadcrumbPage>
                            </BreadcrumbItem>
                          </BreadcrumbList>
                        </Breadcrumb>
                      </div>
                    </header>
                    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4 pt-0">
                      <Form {...form}>
                        <form
                          onSubmit={form.handleSubmit(onSubmit)}
                          className="space-y-6"
                        >
                          <FormField
                            control={form.control}
                            name="trait"
                            render={({ field }) => (
                              <FormItem>
                                <FormLabel>
                                  wondyにはどのような特徴が必要でしょうか？
                                </FormLabel>
                                <FormControl>
                                  <Textarea
                                    placeholder="特徴を入力してください"
                                    className="resize-none"
                                    {...field}
                                  />
                                </FormControl>
                              </FormItem>
                            )}
                          />
                          <DialogFooter>
                            <Button type="submit">Submit</Button>
                          </DialogFooter>
                        </form>
                      </Form>
                    </div>
                  </main>
                </SidebarProvider>
              </DialogContent>
            </Dialog>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}
